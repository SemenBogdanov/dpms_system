# Local llama.cpp connector

Private VPS-to-Mac transport was activated with explicit approval on 2026-09-17.
The application version is unchanged; model-profile registration and full audit-job
acceptance remain separate gates. See `ACTIVATION.md` for verified results and
rollback, and `GATEWAY.md` for gateway design. Never publish the unauthenticated
llama-server with Serve or Funnel. The preparation steps below are historical;
do not reapply quarantine to an active connector without intending to stop it.

## Host prerequisites

- Ubuntu 22.04 production host, nftables, and the official stable Tailscale package.
- Existing DPMS healthcheck passes before and after infrastructure changes.
- User explicitly authorizes adding this VPS to their tailnet.
- No application release, database migration, global firewall flush, DNS change,
  subnet routing, exit-node routing, or Tailscale SSH is needed at this checkpoint.

## Quarantine

Install `tailscale-quarantine.nft` as
`/etc/dpms/local-llm/tailscale-quarantine.nft` (root owned, mode 0644).
Install `dpms-tailnet-quarantine.service` under `/etc/systemd/system/` and
`tailscaled-quarantine.conf` as
`/etc/systemd/system/tailscaled.service.d/dpms-quarantine.conf`.

Validate with `nft --check -f` before applying. Enable/start the quarantine unit
and reload systemd units before initiating login. The drop-in makes future
tailscaled starts require a successfully loaded guard. These rules affect only
the `tailscale0` interface and their own `inet dpms_llm_tailnet_guard` table,
including forwarded Docker traffic and both IP address families. Other host
interfaces retain their existing policy. Reapplying the file replaces only its
own table contents in a single nft transaction.

`RemainAfterExit` is not a continuous firewall monitor. Check the actual table,
hooks and rules immediately before login and after authentication; do not rely
on the unit's `active` state. An unrelated firewall reload could remove rules
without changing that state. No firewall reload is allowed during this checkpoint.
The guard protects kernel-path traffic, not privileged daemon/userspace APIs;
tailnet ACL review remains mandatory before enabling the connector.

Initiate bounded browser login with:

```sh
sudo tailscale up --hostname=dpms-local-llm --accept-dns=false \
  --accept-routes=false --shields-up --ssh=false \
  --advertise-exit-node=false --timeout=20s
```

The browser approval URL is transient and must not be stored in project notes.
Authentication is not proof that the model endpoint is reachable. The quarantine
must still block application traffic after successful login.
The CLI timeout does not cancel the pending browser login. Leave the guard in
place and inspect status separately; use `tailscale down` for an explicit stop.

## Preparation And Acceptance Gates

1. Confirm the user-selected tailnet and review existing grants/ACLs. A narrow
   added allow rule does not override a broad existing allow-all rule.
2. Add an authenticated loopback-only gateway on the Mac. Permit only the required
   model API methods/paths, bound payloads and timeouts, disable administrative
   routes and content logging, and keep credentials out of source and arguments.
3. Configure private HTTPS Serve, never public Funnel, and restrict it to the
   approved VPS identity. Do not change the user's existing llama-server process.
4. Replace quarantine with an explicit allow policy limited to that endpoint;
   preserve IPv6 and forwarded-traffic protections. Verify actual Docker routing
   and hostname resolution without replacing the production host's DNS.
5. Register the HTTPS origin in backend and audit-worker runtime allowlists while
   preserving other configured origins, and create a separately verified DPMS
   model profile. Do not weaken the existing HTTPS or certificate checks.
6. Run a synthetic request through the real audit worker. Test denied clients,
   absent/wrong credentials, blocked management paths, unavailable/sleeping Mac,
   pause/retry behavior, and no fallback to an external model.
7. Only then enable user-triggered processing of approved real documents. Files
   and results still reside in production DPMS; this is not an air-gapped system.

## Safe stop

`tailscale down` stops this connection without changing the DPMS release. Leave
the quarantine installed until the next reviewed activation attempt. Do not
remove the guard while the node is connected, and do not use `nft flush ruleset`,
`tailscale serve reset`, or a global tailnet policy replacement.
