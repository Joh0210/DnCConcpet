# Tech-Stack

Ziel: ein eigenes „D&D Beyond“ – Wiki, Charakter-Editor und Räume zum gemeinsamen Spielen vor Ort. Läuft auf einem Raspberry Pi 3 hinter Cloudflare.

Dieser Python-Code ist der **Prototyp** der Engine. Hier wird das Design erprobt; die Tests dienen später als Spezifikation für den TypeScript-Port.

## Grundlage

| Was | Was es ist | Warum |
|---|---|---|
| **TypeScript** | JavaScript mit Typen | Eine Sprache für Server und Browser. |
| **Node.js (LTS)** | Laufzeitumgebung für JS/TS auf dem Server | Führt den Server auf dem Pi aus. |
| **pnpm** | Paketmanager | Schnell, spart Speicherplatz, kann Monorepos. |
| **Monorepo** | Alle Teile in einem Repo, als einzelne Pakete | Server und Web teilen sich Engine und Typen. |

## Pakete

| Paket | Was es ist | Warum |
|---|---|---|
| `packages/engine` | Die Regel-Engine (Port dieses Prototyps), ohne Abhängigkeiten | Läuft im Browser (sofortige Vorschau) und auf dem Server (verbindliches Ergebnis). |
| `packages/content` | Spielinhalte als YAML + Parser | Eine Quelle für Regeln **und** Wiki. |
| `packages/protocol` | Nachrichtentypen + Schemas | Client und Server sprechen garantiert dieselbe Sprache. |
| `apps/server` | Der Server | Login, Speichern, Räume; liefert die Web-App aus. |
| `apps/web` | Die Web-App | Wiki, Editor, Raum-Ansicht. |

## Frontend

| Was | Was es ist | Warum |
|---|---|---|
| **React** | UI-Bibliothek | Baut die Oberfläche aus Komponenten. |
| **Vite** | Build-Tool | Schneller Entwicklungsserver; baut statische Dateien – braucht auf dem Pi nichts. |
| **PWA** (`vite-plugin-pwa`) | Web-App, die sich wie eine App installieren lässt | Am Tisch auf dem Handy wie eine echte App. |
| **Mantine** | Fertige UI-Komponenten | Viele Formular-Bausteine für den Charakter-Editor. |
| **TanStack Router** | Routing | Welche URL zeigt welche Seite – typsicher. |
| **TanStack Query** | Datenabruf mit Cache | Lädt Serverdaten, hält sie aktuell, vermeidet doppelte Abrufe. |

## Backend

| Was | Was es ist | Warum |
|---|---|---|
| **Fastify** | Web-Server-Framework | Schlank und schnell – wichtig auf dem Pi. |
| **REST** | Normale HTTP-Aufrufe | Für Laden/Speichern (Charaktere, Wiki). |
| **WebSocket** (`@fastify/websocket`) | Dauerhafte Verbindung zwischen Client und Server | Für die Räume: Änderungen (z. B. HP) sehen alle sofort. |
| **zod** | Schema-Validierung | Prüft alles, was reinkommt; die Typen kommen gratis mit. |
| **SQLite** (`better-sqlite3`) | Datenbank in einer einzigen Datei | Kein eigener DB-Server nötig, leicht zu sichern. |
| **Drizzle** | ORM (Datenbank-Zugriff in TS) | Typsichere Abfragen und Migrationen. |

### Räume

Der Server hält jeden Raum im Speicher. Ein Client schickt eine Aktion → der Server prüft sie mit der Engine → sendet die Änderung an alle im Raum. Der Server hat damit immer das letzte Wort.

## Zugang & Accounts

| Was | Was es ist | Warum |
|---|---|---|
| **Cloudflare Tunnel** (`cloudflared`) | Verbindung vom Pi zu Cloudflare | Erreichbar aus dem Internet, ohne Ports am Router zu öffnen. |
| **Cloudflare Zero Trust Access** | Login vor der App (Google) | Nur freigegebene Personen kommen überhaupt rein. Ersetzt ein eigenes Login. |
| **jose** | JWT-Bibliothek | Prüft das signierte Token von Cloudflare (`Cf-Access-Jwt-Assertion`). Nie nur dem E-Mail-Header trauen. |
| **Tabelle `users`** | Accounts der App, Schlüssel ist die E-Mail | Wird beim ersten Besuch angelegt; hält Anzeigename und Rolle. |
| **Dev-Modus** (`AUTH_MODE=dev`) | Ersatz-Login für lokal | Lokal gibt es kein Cloudflare. Startet in Produktion nicht. |

Cloudflare entscheidet, **wer reinkommt**. Die App entscheidet, **was jemand darf**.

## Tests

| Was | Was es ist | Warum |
|---|---|---|
| **Vitest** | Test-Framework | Die Python-Tests werden hierhin übertragen. |

## Betrieb

| Was | Was es ist | Warum |
|---|---|---|
| **Raspberry Pi 3** (64-Bit OS) | Der Server-Rechner | Günstig, sparsam. 64 Bit für aktuelles Node. |
| **Build auf dem PC** | Bauen woanders, nur Ergebnis kopieren | Der Pi hat zu wenig RAM zum Bauen. |
| **systemd** | Dienst-Verwaltung von Linux | Startet den Server automatisch, auch nach Absturz. |
| **Bindung an `127.0.0.1`** | Server lauscht nur lokal | Nur `cloudflared` erreicht ihn – niemand umgeht den Login. |
| **USB-SSD** | Speicher statt SD-Karte | SD-Karten gehen bei vielen Schreibzugriffen kaputt. |

## Bewusst nicht

| Was | Warum nicht |
|---|---|
| **Next.js** | Server-Rendering wird nicht gebraucht, keine eingebauten WebSockets, mehr RAM. |
| **Liveblocks** | Cloud-Dienst für geteilten Client-Zustand; hier muss der Server mit der Engine entscheiden. |
| **Rust** | Leistung reicht mit Node; Port wäre deutlich aufwendiger. |
