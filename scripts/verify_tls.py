"""Live release gate: default Python and bundled CA stores must reject eMudhra."""

import contextlib
import importlib
import importlib.metadata
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

HOSTS = (
    "https://dv-g3b-emudhra.we-have-a-problem.com/",
    "https://dv-g3b-aaa-emudhra.we-have-a-problem.com/",
    "https://www.python.org/",
)


def certificate_failure(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ssl.SSLCertVerificationError):
            return True
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            return True
        exc = getattr(exc, "reason", None) or exc.__cause__ or exc.__context__
    return False


def check(name, get):
    for index, url in enumerate(HOSTS):
        try:
            get(url)
        except Exception as exc:
            if index == 2 or not certificate_failure(exc):
                raise RuntimeError(
                    f"{name}: unexpected failure at {url}: {exc}"
                ) from exc
            print(
                json.dumps(
                    {"verifier": name, "url": url, "result": "certificate rejected"}
                ),
                flush=True,
            )
        else:
            if index != 2:
                raise RuntimeError(f"{name}: compromised chain accepted: {url}")
            print(
                json.dumps(
                    {"verifier": name, "url": url, "result": "valid HTTPS accepted"}
                ),
                flush=True,
            )


def urllib_get(url, context=None):
    with urllib.request.urlopen(url, context=context, timeout=20) as response:
        response.read(1)


print(ssl.OPENSSL_VERSION, ssl.get_default_verify_paths(), flush=True)
check("stdlib/system", urllib_get)
for module_name in ("certifi", "pip._vendor.certifi"):
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        continue
    print(module_name, module.where(), flush=True)
    context = ssl.create_default_context(cafile=module.where())
    check(module_name, lambda url, context=context: urllib_get(url, context))
for module_name in ("requests", "httpx", "pip._vendor.requests"):
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError:
        continue
    check(module_name, lambda url, module=module: module.get(url, timeout=20))
for package in ("certifi", "pip", "httpx", "requests"):
    with contextlib.suppress(importlib.metadata.PackageNotFoundError):
        print(package, importlib.metadata.version(package), flush=True)

if shutil.which("uv"):
    for url in HOSTS[:2]:
        probe = subprocess.run(
            [
                "uv",
                "--no-cache",
                "pip",
                "install",
                "--dry-run",
                "--python",
                sys.executable,
                "--index-url",
                url,
                "ca-security-release-nonexistent-probe",
            ],
            env={**os.environ, "UV_HTTP_RETRIES": "0"},
            capture_output=True,
            text=True,
            timeout=60,
        )
        if probe.returncode == 0 or not any(
            marker in probe.stderr
            for marker in (
                "UnknownIssuer",
                "invalid peer certificate",
                "certificate verify failed",
            )
        ):
            raise RuntimeError(f"uv did not reject the certificate: {probe.stderr}")
        print(
            json.dumps(
                {"verifier": "uv", "url": url, "result": "certificate rejected"}
            ),
            flush=True,
        )
