"""Technical SHA representation fix for the original exact E01 LF exception v2."""
import hashlib
import re

ID='storygen.e01.template-identity/2.0'
EMBEDDED='sha256:e16746b40344d6c5b5265988e0328a0bf7277be86f1c335156eae07e29c82826'
LIVE='sha256:cafb64e0e9e5fd2503054b3479593fae39cbdfd52338ce8af9bb4664a8eb05bd'

def digest(payload):return 'sha256:'+hashlib.sha256(payload).hexdigest()

def compare(live_template,embedded_sha256):
    if not isinstance(embedded_sha256,str) or not re.fullmatch(r'(sha256:)?[0-9a-f]{64}',embedded_sha256):
        raise ValueError('Exact SHA256 template identity required')
    expected='sha256:'+embedded_sha256.removeprefix('sha256:')
    actual=digest(live_template.encode());exception=None
    if actual!=expected:
        if expected!=EMBEDDED or actual!=LIVE or digest((live_template+'\n').encode())!=expected:
            raise ValueError('Live template differs from the verified embedded template')
        exception='verified_embedded_template_has_one_additional_trailing_LF'
    return dict(embedded_template_sha256=expected,live_template_sha256=actual,compatibility_exception=exception)
