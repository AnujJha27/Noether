#!/usr/bin/env python3
import pathlib
import sys

source = pathlib.Path(sys.argv[-1]).read_text(encoding="utf-8")
required = "#check (DFTCert.Example.certificate : (verify (Fin 1) DFTCert.Example.manifest).approved = true)"
binding = "#check (DFTCert.Example.canonicalManifestSha256_bound : DFTCert.Example.canonicalManifestSha256 = \""
if required not in source or binding not in source:
    print("missing exact certificate check")
    raise SystemExit(1)
print("DFTCert.Example.certificate : expected certificate type")
