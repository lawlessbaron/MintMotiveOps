"""Walks every registered GET route with a logged-in session and reports
status codes / tracebacks. Not a replacement for real usage testing, but
catches import errors, missing templates, and undefined Jinja variables
across the whole app in one shot."""
import sys
from app import create_app

app = create_app()
app.config["TESTING"] = True

with app.test_client() as c:
    # log in
    resp = c.post("/login", data={"email": "lawlessbaron@gmail.com", "password": sys.argv[1]}, follow_redirects=True)
    print("LOGIN:", resp.status_code, "OK" if b"Dashboard" in resp.data or resp.status_code == 200 else "?")

    skip_prefixes = ("/static", "/public")
    failures = []
    checked = 0
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if "GET" not in rule.methods:
            continue
        if any(str(rule).startswith(p) for p in skip_prefixes):
            continue
        if "<" in rule.rule:
            continue  # skip parameterized routes in this first pass
        checked += 1
        try:
            resp = c.get(rule.rule)
            status = resp.status_code
            if status >= 400:
                failures.append((rule.rule, status, resp.data[:300]))
        except Exception as e:
            failures.append((rule.rule, "EXC", repr(e)))

    print(f"\nChecked {checked} static routes.")
    if failures:
        print(f"\n{len(failures)} FAILURES:")
        for rule, status, detail in failures:
            print(f"  {rule} -> {status}")
            print(f"    {detail}")
    else:
        print("All static routes returned < 400.")

    # now check a handful of parameterized routes with id=1
    param_routes = [r.rule for r in app.url_map.iter_rules() if "GET" in r.methods and "<int:" in r.rule and not str(r).startswith(("/static", "/public"))]
    print(f"\nParameterized routes found: {len(param_routes)}")
    for rule in sorted(param_routes):
        print(" ", rule)
