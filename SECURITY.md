# Security Policy

## Reporting a Vulnerability

Report vulnerabilities to eltonboehnen@gmail.com. Do not open a public issue
for an unpatched security problem — email first so a fix can land before
details are public.

## Scope Notes

Doc_Chunker runs locally (CLI) or as a local Flask server
(`http://localhost:5050` by default) with no built-in authentication — it is
designed for single-user local/LAN use, not for exposure on an untrusted
network. If you deploy the Flask UI anywhere reachable by others, put it
behind your own auth layer first.
