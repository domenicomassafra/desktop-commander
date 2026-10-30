# Desktop Commander: hosting owner (#477)

## Decisione e provenienza — 23 ottobre 2026

Il fork GitHub deriva da wonderwhy-er/DesktopCommanderMCP, MIT, commit
f5c86e56e5192b25c7d8de9ed8109873385912ef (v0.3.1). Nessuna modifica a
src/, strumenti o autenticazione upstream. Il workflow owner-upstream-sync
aggiorna ogni giorno main con merge standard: conflitti o test falliti
impediscono il push, mai force. Provare gli aggiornamenti prima del deploy.

Riusi, senza server o autenticazione scritti da noi:

- ni-c/mcp-hub 0.11.6, MIT, e184c4e33de950e0b3f0d66bc8e7161acb905c2b:
  aggregazione **stdio nativa**, nessun listener e nessun authorization server.
  https://mcp-hub.ni-c.de/reference/environment#in-stdio-mode
- [supercorp-ai/supergateway 4.2.1](https://github.com/supercorp-ai/supergateway/releases/tag/v4.2.1), MIT,
  commit a78bd90804d3080e8268961949f22575b34826f0: stdio → HTTP autenticato
  solo su Tailscale Studio. Binario darwin-arm64 verificato con SHA256SUMS
  (`fee4ca40ded90c0429aa64fbc75a819c67828df56a36d8edd8c78712d2f7e698`)
  e GitHub attestation; installare come `supergateway-4.2.1` con le licenze.
- [openai/tunnel-client 0.0.18](https://github.com/openai/tunnel-client/releases/tag/v0.0.18), Apache-2.0,
  commit 274a5588414819f063d27100a4fb1096aae3830f. Binario dedicato nel runtime,
  non sostituisce quello usato da altri servizi. Release linux-amd64.zip
  SHA256 `3c82307316acd93c88a384b62af1d81d3f4cb0efa975f9c0bfaef922866a04c4`.
  https://github.com/openai/tunnel-client/releases/latest
  https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
  https://github.com/openai/tunnel-client/blob/master/docs/onboarding.md

Il candidato TransductiveScience/desktop-commander-mcp, MIT,
04ea82e8e064a7aa687971e05e3b31d5d2f89489, è fermo alla 0.2.47. Scartato
cloudflare-auth-worker: /token accetta refresh_token arbitrari non vuoti,
code JSON base64 modificabile e /authorize senza autentica owner. Fonti:
cloudflare-auth-worker/src/index.js a quel commit; discussioni upstream
#617 (31 luglio–18 settembre 2026) e #664 (30 agosto 2026).

**Licenza transitiva:** sharp/libvips upstream include
@img/sharp-libvips-darwin-arm64 LGPL-3.0-or-later. Segnalata prima del deploy;
nessuna modifica ai binari, conservare licenze e avvisi originali.

## Topologia privata e invarianti

MCP resta necessario per esporre a ChatGPT la discovery e le chiamate remote
agli strumenti di file e processi. Una CLI locale non fornisce al Secure MCP
Tunnel gli schemi degli strumenti né il protocollo richiesto dal connettore.
La motivazione è riportata anche nella configurazione della unit systemd e
nel generatore della configurazione dell'hub.

ChatGPT → OpenAI Secure MCP Tunnel → client ufficiale MiniPC → hub stdio →
Desktop Commander stdio MiniPC oppure Supergateway Studio su
100.99.195.87:9197/mcp (Tailscale, API key). Studio è elencato per primo.
Un connettore offre list_servers/list_tools/get_tool_schema/call_tool:
server=studio oppure server=minipc. Non sono i vecchi execute_command(host).
Nessun account, relay o chiamata automatica a desktopcommander.app.

Tunnel dedicato: tunnel_6ada9565bc9081918acfcd3dee77b650. Non riutilizzare
tunnel CoS/Obsidian/Browser Use. Il client apre solo connessioni uscenti a
OpenAI. Non esiste URL prodotto pubblico e non serve un login OAuth esterno.
La vecchia soluzione Cloudflare/Funnel/OAuth è superata dalla decisione owner.
Il listener health/admin è solo 127.0.0.1:8498; l'hub non ascolta su 8497.
Usare una sola istanza tunnel-client per questo ID (affinità stdio).

Studio: LaunchAgent it.domenico.desktop-commander, utente domenico,
Supergateway solo sull'IP Tailscale, sandbox macOS che nega sudo/su/visudo/
security. MiniPC: unit utente desktop-commander.service con NoNewPrivileges.
Nessun sudo nell'installer. DESKTOP_COMMANDER_DISABLE_TELEMETRY=1,
DC_FLAG_URL=data:application/json,... e --no-onboarding sono opzioni native.
NODE_DEBUG=net è diagnostica connessioni senza payload HTTP; disattivarla
fuori dalla finestra di accettazione. Non è un firewall per bloccare comandi
espliciti dell'owner.

## Installazione ufficiale e proiezione

Usare il pacchetto npm ufficiale `@wonderwhy-er/desktop-commander@0.3.1`
(MIT, pubblicato il 22 ottobre 2026). Su **ciascun host**, con la guardia
risorse, eseguire `sh hosting/install-upstream.sh`. Il package resta
fissato in `~/.local/opt/desktop-commander/upstream-0.3.1/` e viene
installato per l'OS locale. Il servizio attivo cambia solo dopo la
proiezione con `hosting/install.py` e il riavvio nativo. Nessun gestore
di promozione, pruning o rollback personalizzato.

Scaricare la release ufficiale tunnel-client corrente e verificarne il digest
GitHub prima dell'estrazione; conservare LICENSE/NOTICE/SPDX. Il writer usa
~/.local/opt/desktop-commander/tunnel-client-0.0.18/tunnel-client. Per un
upgrade aggiornare insieme percorso unit/writer e prove: non cambiare
il client globale di altri servizi. Leggere sempre help quickstart/init/doctor.

Proiettare esclusivamente dal writer:

```sh
release="$HOME/.local/opt/desktop-commander/upstream-0.3.1/node_modules/@wonderwhy-er/desktop-commander"
secret env DESKTOP_COMMANDER_API_TOKEN -- python3 hosting/install.py studio --release "$release"
secret env DESKTOP_COMMANDER_API_TOKEN COMPUTER_MCP_OPENAI_RUNTIME_KEY -- python3 hosting/install.py minipc --release "$release"
```

Verificare MCP `initialize`, `tools/list` e `start_process(hostname)`
dopo il riavvio di launchd (Studio) e systemd user (MiniPC).

COMPUTER_MCP_OPENAI_RUNTIME_KEY è una runtime key OpenAI dedicata con Tunnels
Read + Use. Proviene dal catalogo age; non è il vecchio token Cloudflare
CHATGPT_COMPUTER_MCP_TUNNEL_TOKEN. Il writer proietta openai-runtime-key 0600
e usa il riferimento file: nel profilo generato da tunnel-client init.
Il valore non compare in argv, unit, log o ambiente del server stdio.
DESKTOP_COMMANDER_API_TOKEN resta nell'env privato del solo hub per Studio:
il suo processo Desktop Commander figlio riceve solo l'ambiente filtrato.
Non cancellare vecchi segreti, DB o stato OAuth: sono dati protetti, non
servizi da lasciare attivi. prepare-secrets.py aggiunge solo API key Studio
con il writer age dotfiles; la chiave OpenAI va creata nell'account owner.

Prima di avviare il trasporto privato ritirare il solo Funnel10000 e fermare
cloudflared-computer-mcp: non spegnere OAuth su un listener ancora pubblico.
Il vecchio backend chatgpt-twohost-mcp resta attivo fino alla prova ChatGPT.

```sh
systemctl --user daemon-reload
systemctl --user enable --now desktop-commander.service
# Al redeploy: restart, senza sovrapporre due client dello stesso tunnel.
~/.local/opt/desktop-commander/tunnel-client-0.0.18/tunnel-client doctor --profile computer-mcp --profile-dir ~/.config/desktop-commander/tunnel-profiles --health.listen-addr 127.0.0.1:0 --explain
curl -fsS http://127.0.0.1:8498/readyz
curl -fsS http://127.0.0.1:8498/health/mcp
python3 -m unittest discover -s hosting -p 'test_*.py' -v
```

## Gesto owner e prova reale

In ChatGPT Plugins → Add custom MCP server, etichetta Computer MCP, Connection
Tunnel, ID dedicato sopra, autenticazione «OAuth o nessuna autenticazione».
Confermare il rischio e premere Crea. Nessuna password o pagina esterna.
Fare discovery soltanto mentre il client è ready: /health/mcp deve osservare
server/discover e tools/list same_child, non soltanto il processo acceso.
Il path /v1/mcp/{id} è un endpoint interno del connector; non usarlo come
URL pubblico api.openai.com e non fare inferenza API a pagamento per provarlo.

Da chat reale sulla nuova app invocare call_tool su server=studio/minipc:
start_process(command=hostname), write_file/read_file con marker univoco
in un file temporaneo della prova, cleanup, sudo -n true (deve fallire).
Conservare ricevute ChatGPT, contatori delivery e diagnostica rete nella
issue #477. La sonda SDK stdio locale non certifica il prodotto ChatGPT.
Solo dopo queste prove migrare consumer e ritirare backend legacy,
bridge Studio, tunnel Cloudflare dedicato e sorgente/runbook ControlCenter,
senza toccare servizi, dati o tunnel Obsidian indipendenti.


## Aggiornamento trasporto owner — 31 ottobre 2026

Il pacchetto ufficiale `@wonderwhy-er/desktop-commander` resta fissato
alla release stabile **0.3.1** su Mac Studio e MiniPC; non ci sono
release stabili successive alla data di questa verifica. Il fork
conserva `src/` e `test/` upstream identici all'originale.

Si aggiornano esclusivamente le dipendenze di trasporto sul MiniPC:

- `@ni-c/mcp-hub` **0.11.7**, con versione e albero dipendenze bloccati
  in `hosting/gateway/package-lock.json`. Installare con `npm ci
  --ignore-scripts` su una directory distinta prima di attivare il nuovo
  hub. Include fix di sicurezza di `body-parser` 2.4.0.
- `openai/tunnel-client` **v0.0.19**, binario ufficiale linux-amd64
  verificato con `SHA256SUMS.txt`, collocato in
  `~/.local/opt/desktop-commander/tunnel-client-0.0.19/` con licenze/SPDX.
  Migliora la recovery dei figli stdio. Non aggiungere i nuovi flag/YAML
  di failure policy al profilo condiviso: il rollback v0.0.18 deve
  continuare a leggere la configurazione esistente.
- `supercorp-ai/supergateway` **4.2.1** resta ultima release stabile e
  Studio non deve essere riavviato per questo upgrade MiniPC.

Conservare come rollback hub 0.11.6, precedente systemd unit, tunnel
0.0.18 e profilo. Preflight: `probe.py` su candidato hub 0.11.7 e
`tunnel-client 0.0.19 doctor`. Cutover sotto lock esclusivo, arrestando
la sola unit `desktop-commander.service`, sostituendo hub e unit, quindi
riavviando e verificando `/readyz`, `doctor` e prova MCP 2/2 host.
In caso di errore ripristinare unit e gateway precedenti e riavviare
il client 0.0.18. Non ri-eseguire il writer `install.py minipc` nel
cutover: riscrive il profilo e richiede espliciti secret gate.
Non cancellare versioni, dati o backup storici.
