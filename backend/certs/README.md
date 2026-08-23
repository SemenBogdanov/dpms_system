# Synology TLS CA bundle

`letsencrypt-gen-y.pem` contains the public Let's Encrypt YR1 and YR2
intermediates plus Root YR cross-signed by ISRG Root X1. It is used only as
additional trust material for the allowlisted Synology connector when the NAS
does not serve its complete certificate chain.

Sources:

- https://letsencrypt.org/certs/gen-y/int-yr1.pem
- https://letsencrypt.org/certs/gen-y/int-yr2.pem
- https://letsencrypt.org/certs/gen-y/root-yr-by-x1.pem

The preferred operational fix is to configure Synology to serve the complete
certificate chain. Never disable TLS verification as a workaround.
