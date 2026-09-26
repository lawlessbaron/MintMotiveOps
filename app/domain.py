"""Ops' own domain, set from Administration → Domain.

With a Railway token on the service (RAILWAY_PROJECT_TOKEN, from the project's
Settings → Tokens; or an account token as RAILWAY_API_TOKEN) the page adds
the domain to this Railway service through Railway's public API and lists the
DNS records to create at whoever manages the domain. Railway gives every
service RAILWAY_PROJECT_ID, RAILWAY_ENVIRONMENT_ID and RAILWAY_SERVICE_ID.

"Check it works" confirms https://<domain> reaches this very app (not just
any server), and only then can visitors on other addresses (such as the
*.up.railway.app one) be sent to the domain, so a typo can't lock anyone out.

Standard library only (urllib, socket, json), like the rest of Ops' helpers.
"""
import json
import os
import re
import secrets
import socket
import ssl
import time
import urllib.error
import urllib.request

RAILWAY_API = "https://backboard.railway.com/graphql/v2"
# Made once when the app is imported; gunicorn --preload imports before the
# workers fork, so every worker answers with the same id.
INSTANCE_ID = secrets.token_hex(12)

_HOST = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def clean_domain(value):
    d = (value or "").strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"[/?#].*$", "", d)
    d = re.sub(r":\d+$", "", d).rstrip(".")
    return d if _HOST.match(d) else None


def zone_of(domain):
    """mintmotive.com.au for ops.mintmotive.com.au (.com.au, .co.uk take three labels)."""
    p = domain.split(".")
    three = len(p) >= 3 and p[-2] in {"com", "net", "org", "co", "gov", "edu", "asn", "id", "ac", "or", "ne", "go"} and len(p[-1]) == 2
    return ".".join(p[-3:] if three else p[-2:])


# Fullest to smallest, so a renamed field in Railway's schema costs detail,
# not the whole feature.
_STATUS_FIELDS = [
    "dnsRecords { hostlabel fqdn zone recordType requiredValue currentValue status purpose } verificationDnsHost verificationToken verified certificateStatus",
    "dnsRecords { hostlabel fqdn zone recordType requiredValue currentValue status } verificationToken certificateStatus",
    "dnsRecords { hostlabel recordType requiredValue currentValue status }",
    "dnsRecords { hostlabel requiredValue }",
]


class RailwayError(Exception):
    def __init__(self, message, schema=False):
        super().__init__(message)
        self.schema = schema


class Railway:
    def __init__(self, env=None, opener=None):
        env = os.environ if env is None else env
        self.ids = {
            "projectId": env.get("RAILWAY_PROJECT_ID", ""),
            "environmentId": env.get("RAILWAY_ENVIRONMENT_ID", ""),
            "serviceId": env.get("RAILWAY_SERVICE_ID", ""),
        }
        if env.get("RAILWAY_PROJECT_TOKEN"):
            self.token = ("project", env["RAILWAY_PROJECT_TOKEN"])
        elif env.get("RAILWAY_API_TOKEN"):
            self.token = ("account", env["RAILWAY_API_TOKEN"])
        else:
            self.token = None
        self.on_railway = all(self.ids.values())
        self.ready = bool(self.on_railway and self.token)
        self.token_kind = self.token[0] if self.token else None
        self._open = opener or (lambda req: urllib.request.urlopen(req, timeout=15))

    def _gql(self, query, variables):
        if not self.ready:
            raise RailwayError("Railway isn't connected: add RAILWAY_PROJECT_TOKEN on this service in Railway.")
        headers = {"Content-Type": "application/json"}
        if self.token[0] == "project":
            headers["Project-Access-Token"] = self.token[1]
        else:
            headers["Authorization"] = f"Bearer {self.token[1]}"
        req = urllib.request.Request(RAILWAY_API, data=json.dumps({"query": query, "variables": variables}).encode(), headers=headers, method="POST")
        try:
            with self._open(req) as res:
                out = json.loads(res.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            try:
                out = json.loads(e.read().decode() or "{}")
            except Exception:
                raise RailwayError(f"Railway answered {e.code}.")
        except Exception:
            raise RailwayError("Couldn't reach Railway's API. Try again in a minute.")
        if out.get("errors"):
            msg = "; ".join(e.get("message", "") for e in out["errors"])
            raise RailwayError(f"Railway: {msg}", schema=bool(re.search(r"Cannot query field|Unknown argument|Unknown type", msg)))
        return out.get("data") or {}

    def _with_status(self, build, variables):
        last = None
        for fields in _STATUS_FIELDS:
            try:
                return self._gql(build(fields), variables)
            except RailwayError as e:
                last = e
                if not e.schema:
                    raise
        raise last

    def list(self):
        data = self._with_status(lambda f: (
            "query domains($projectId: String!, $environmentId: String!, $serviceId: String!) {"
            " domains(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId) {"
            " serviceDomains { domain } customDomains { id domain status { %s } } } }" % f), self.ids)
        d = data.get("domains") or {}
        return {
            "service_domains": [x.get("domain") for x in d.get("serviceDomains") or []],
            "custom_domains": [_shape(x) for x in d.get("customDomains") or []],
        }

    def add(self, domain):
        data = self._with_status(lambda f: (
            "mutation add($input: CustomDomainCreateInput!) { customDomainCreate(input: $input) {"
            " id domain status { %s } } }" % f), {"input": {**self.ids, "domain": domain}})
        return _shape(data.get("customDomainCreate") or {})


def _shape(d):
    s = d.get("status") or {}
    records = []
    for r in s.get("dnsRecords") or []:
        records.append({
            "type": re.sub(r"^DNS_RECORD_TYPE_", "", str(r.get("recordType") or "CNAME")),
            "host": r.get("hostlabel") or "@",
            "value": r.get("requiredValue") or "",
            "current": r.get("currentValue") or "",
            "ok": bool(re.search(r"PROPAGATED|VALID|SUCCESS", str(r.get("status") or ""), re.I)),
        })
    token = s.get("verificationToken")
    if token and not any(r["type"] == "TXT" for r in records):
        domain = d.get("domain") or ""
        zone = next((r.get("zone") for r in s.get("dnsRecords") or [] if r.get("zone")), None) or zone_of(domain)
        label = domain[: -len(zone) - 1] if domain.endswith("." + zone) else ""
        host = s.get("verificationDnsHost") or ("_railway-verify" + (f".{label}" if label else ""))
        value = token if "railway-verify=" in token else f"railway-verify={token}"
        records.append({"type": "TXT", "host": host, "value": value, "current": "", "ok": bool(s.get("verified"))})
    cert = s.get("certificateStatus")
    return {"id": d.get("id"), "domain": d.get("domain"), "records": records,
            "certificate": re.sub(r"^CERTIFICATE_STATUS_TYPE_", "", cert).lower().replace("_", " ") if cert else None}


def probe(domain, opener=None):
    """Does https://<domain> reach this very app? Returns (ok, message)."""
    opener = opener or (lambda req: urllib.request.urlopen(req, timeout=8))
    try:
        with opener(urllib.request.Request(f"https://{domain}/.well-known/ops-instance")) as res:
            body = res.read().decode().strip()
        if body == INSTANCE_ID:
            return True, f"https://{domain} reaches this app, with a valid certificate."
        return False, f"https://{domain} answered, but not from this app. The DNS record may still point somewhere else."
    except urllib.error.HTTPError as e:
        return False, f"https://{domain} answered {e.code}, not from this app. The DNS record may still point somewhere else."
    except urllib.error.URLError as e:
        why = e.reason
        if isinstance(why, socket.gaierror):
            return False, f"{domain} doesn't resolve yet. Add the DNS records, then allow up to an hour."
        if isinstance(why, ssl.SSLError):
            return False, f"{domain} reaches a server, but its HTTPS certificate isn't ready. Railway issues it a few minutes after DNS is right."
        return False, f"Couldn't reach https://{domain} ({why})."
    except Exception as e:  # timeouts and the like
        return False, f"Couldn't reach https://{domain} ({e})."


def resolves_to(domain):
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(domain, 443, proto=socket.IPPROTO_TCP)})
    except Exception:
        return []


class DomainSettings:
    """The saved domain and redirect switch, re-read from the database at most
    every 30 seconds (gunicorn runs several workers; a change saved in one
    reaches the others within that time)."""

    def __init__(self, ttl=30):
        self.ttl, self._at, self._val = ttl, 0.0, (None, False)

    def get(self, db):
        if time.monotonic() - self._at > self.ttl:
            try:
                row = db.execute("SELECT primary_domain, domain_redirect FROM company_settings ORDER BY id LIMIT 1").fetchone()
                self._val = ((row["primary_domain"] or None), bool(row["domain_redirect"])) if row else (None, False)
            except Exception:
                self._val = (None, False)
            self._at = time.monotonic()
        return self._val

    def forget(self):
        self._at = 0.0


settings = DomainSettings()
