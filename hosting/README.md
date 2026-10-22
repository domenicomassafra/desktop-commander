# Desktop Commander: hosting owner (#477)

## Decisione e provenienza — 22 ottobre 2026

Il fork GitHub deriva direttamente da wonderwhy-er/DesktopCommanderMCP,
MIT, commit f5c86e56e5192b25c7d8de9ed8109873385912ef (release v0.3.1).
Nessuna modifica a src/, strumenti o autenticazione upstream.
Il workflow owner-upstream-sync aggiorna giornalmente main con merge normale;
conflitti o test falliti impediscono il push, mai force. Gli aggiornamenti
vanno nuovamente provati prima di proiettare una release sui computer.

Il candidato TransductiveScience/desktop-commander-mcp, MIT,
04ea82e8e064a7aa687971e05e3b31d5d2f89489, offre HTTP nativo ma è fermo
alla 0.2.47. Scartato il suo cloudflare-auth-worker: /token accetta qualsiasi
refresh_token non vuoto, i code sono JSON base64 modificabile dal client e
/authorize non autentica l'owner. Non esporlo su Internet.
Fonti: file cloudflare-auth-worker/src/index.js a quel commit; discussioni
upstream #617 (31 luglio–18 settembre 2026) e #664 (30 agosto 2026).
Non abbiamo pubblicato dettagli nei repository di terzi.

Il trasporto, OAuth e l'aggregazione sono pacchetti mantenuti, non server propri:

- ni-c/mcp-hub 0.11.6, MIT, commit e184c4e33de950e0b3f0d66bc8e7161acb905c2b:
  OAuth/OIDC password, DCR/PKCE, refresh persistente, aggregatore /hub.
  https://mcp-hub.ni-c.de/guide/getting-started
  https://mcp-hub.ni-c.de/guide/security
  https://mcp-hub.ni-c.de/reference/environment
- supercorp-ai/supergateway v4.2.0, MIT,
  2b7504bbb63634f2aeb5083461bd8c9ff0d9a2c8:
  stdio → Streamable HTTP autenticato su Studio. Binario darwin-arm64
  verificato con SHA256SUMS e gh attestation verify (exit 0).

**Licenza transitiva:** sharp/libvips distribuito da upstream include
@img/sharp-libvips-darwin-arm64 LGPL-3.0-or-later. Nessuna modifica ai binari;
conservare package.json, licenze e avvisi originali. Segnalato al coordinatore
prima del deploy. Il codice hosting owner resta separato.

## Topologia e invarianti

ChatGPT → Cloudflare Tunnel owner → MiniPC :8497 /hub → due server:
Studio via Tailscale 100.99.195.87:9197/mcp (Supergateway + Desktop Commander),
MiniPC via stdio locale (Desktop Commander).
L'aggregatore offre list_servers/list_tools/get_tool_schema/call_tool:
server=studio o server=minipc sceglie il computer senza raddoppiare connettori.
Studio è elencato per primo. Nessun relay/account Desktop Commander.

Studio: LaunchAgent it.domenico.desktop-commander, utente domenico,
bind solo sull'indirizzo Tailscale, chiave API dal catalogo MINIPC_MCP_TOKEN,
sandbox macOS che nega sudo/su/visudo/security. MiniPC: unit utente
systemd desktop-commander.service, NoNewPrivileges=yes, udodo.
Nessun sudo nell'installer. Il protocollo Studio attraversa la rete tailnet
cifrata; non esporre :9197 su hostname pubblico.

DESKTOP_COMMANDER_DISABLE_TELEMETRY=1 e DC_FLAG_URL=data:application/json,...
usano opzioni native: niente flag remoti né telemetria. --no-onboarding
impedisce UI/account remoti. Queste impostazioni non sono una firewall policy
contro eventuali comandi espliciti dell'utente: la prova di rete resta necessaria.

Il vecchio Computer MCP (:8496, tunnel cloudflared-computer-mcp) rimane
acceso e invariato finché la prova da ChatGPT non riesce. Non ritirare i file
ControlCenter né ripulire Obsidian prima di quella prova.

## Build e proiezione

Build e dipendenze si preparano sul MiniPC tramite workload_launcher.py build.
Usare package-lock.json upstream; npm ci --ignore-scripts quando la memoria
lo consente. Su questo MiniPC npm ci è stato terminato (exit 247, circa 900 MB
registrati dal cgroup), anche con heap 256 MB; Bun 1.4.2 ha completato lo
stesso albero. Non alzare i limiti della guardia. bun.lock generato è temporaneo,
non sostituisce il lock upstream.

sh hosting/build.sh compila il runtime con declaration=false: la disposizione
Bun dei moduli arg causa TS2742 durante emissione .d.ts, irrilevanti al servizio.
Nessuna modifica ai sorgenti upstream per aggirarlo.
Per Studio preparare le dipendenze sul MiniPC con bun install --ignore-scripts
--os=darwin --cpu=arm64, mantenendo vendor/ e i pacchetti @img della piattaforma.
Non copiare i binari Linux sul Mac. Conservare dist/, package.json, vendor/,
node_modules/ e hosting/ sotto ~/.local/opt/desktop-commander/releases/<SHA>/.
Installare hosting/gateway/package.json a versione esatta nel percorso
~/.local/opt/desktop-commander/gateway/ sul MiniPC.

Proiettare tramite questo writer, mai modificando a mano i file generati:

    secret env MINIPC_MCP_TOKEN -- python3 <release>/hosting/install.py studio --release <release>
    secret env MINIPC_MCP_TOKEN MINIPC_MCP_OAUTH_PASSWORD -- python3 <release>/hosting/install.py minipc --release <release>

La password esistente viene trasformata in bcrypt senza log o argomenti CLI;
config/env e chiave API hanno mode 0600, directory 0700. L'hub non passa i
segreti OAuth ai processi stdio. I dati OAuth persistenti non sono cache:
non eliminarli per aggiornare o riparare il servizio.

    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/it.domenico.desktop-commander.plist
    systemctl --user daemon-reload
    systemctl --user enable --now desktop-commander.service

Su ri-deploy usare kickstart -k per il LaunchAgent già caricato e restart
per systemd. Prima validare plist con plutil -lint e testare il writer:

    python3 -m unittest discover -s hosting -p 'test_*.py' -v
    DESKTOP_COMMANDER_DISABLE_TELEMETRY=1 node test/test-feature-flags-timeout.js

Non eseguire i test upstream con una HOME personale: alcuni possono mutare
configurazione. La suite timeout qui usa risorse temporanee proprie.

## Gate pubblico e prova owner

Hostname proposto: desktop-commander.dichiarazionipubbliche.it → ingresso
Cloudflare http://127.0.0.1:8497, sul tunnel dedicato dell'owner (stesso tunnel
può avere due ingressi, mantenendo intatto computer-mcp → :8496).
Prima di richiedere login: /livez 200, /hub senza token 401, discovery OAuth
raggiungibile e non pubblicizzare domini desktopcommander.app/transductive.

Poi, nell'account ChatGPT principale, Settings → Apps → Create app:
URL https://desktop-commander.dichiarazionipubbliche.it/hub, OAuth;
autorizzare una sola volta con la password owner del connettore.
Da chat reale usare call_tool con server=studio e server=minipc per hostname,
write_file/read_file in un file temporaneo creato per la prova, e sudo -n true
che deve fallire. Conservare ricevute reali e log di rete nella issue #477.
Solo allora migrare skill/consumer e ritirare il vecchio servizio, tunnel,
bridge Studio, sorgente ControlCenter e branding/test computer nel fork
Obsidian, mantenendo i servizi e dati Obsidian indipendenti.
