# Pluggable Ticket System — Architecture Design

## 1. Core Idea

Everything that can change (notification channel, message source, storage, auth)
is treated as a **plugin behind an interface**. The core domain (tickets,
conversations, SLAs, assignment) never imports a concrete vendor SDK — it only
depends on abstract **ports**. Concrete vendors (Slack, Telegram, WhatsApp,
Gmail, IMAP, Outlook…) are **adapters** that implement those ports and are
wired in at startup via a **plugin registry**, driven by config.

This is the classic **Ports & Adapters (Hexagonal) Architecture**, combined
with an **event bus** so that adapters don't call each other directly either —
they only publish/subscribe to domain events. That's what lets you run Slack
*and* Telegram *and* three mailboxes at once, and drop/add one without
touching the others.

```
                         ┌───────────────────────────────┐
                         │        CORE DOMAIN            │
                         │  Ticket, Conversation, SLA,   │
                         │  Assignment, Rules Engine     │
                         └───────────────┬───────────────┘
                                 ports (interfaces)
              ┌───────────────────────────┼───────────────────────────┐
              │                           │                           │
      INBOUND PORTS                EVENT BUS (pub/sub)          OUTBOUND PORTS
   (MessageSource)                                          (NotificationChannel,
              │                                               TicketStore, etc.)
   ┌──────────┼──────────┐                          ┌────────────────┼────────────────┐
   │          │          │                          │                │                │
Gmail API   IMAP     Outlook API                  Slack          Telegram          WhatsApp
 Adapter   Adapter    Adapter                     Adapter         Adapter           Adapter
```

---

## 2. Layers

| Layer | Responsibility | Depends on |
|---|---|---|
| **Domain (core)** | Ticket lifecycle, business rules, SLA timers, routing logic | Nothing external — pure logic |
| **Application (use cases)** | Orchestrates domain + ports: `CreateTicketFromMessage`, `NotifyAssignee`, `CloseTicket` | Domain + Ports (interfaces only) |
| **Ports** | Interfaces the application depends on | Nothing (just contracts) |
| **Adapters (plugins)** | Concrete implementations: Slack SDK, IMAP client, Postgres repo | Ports + external SDKs |
| **Composition root** | Reads config, instantiates the right adapters, injects them | Everything (only place that "knows" concrete classes) |

This is the key rule: **dependencies point inward.** Adapters know about the
domain's interfaces; the domain knows nothing about Slack or Gmail.

---

## 3. Core Ports (interfaces)

```typescript
// ---- Inbound: anything that can produce a message that becomes a ticket ----
interface MessageSource {
  id: string;                       // e.g. "gmail-support-inbox"
  start(onMessage: (msg: InboundMessage) => Promise<void>): Promise<void>;
  stop(): Promise<void>;
}

interface InboundMessage {
  sourceId: string;
  externalId: string;
  from: string;
  subject?: string;
  body: string;
  attachments?: Attachment[];
  receivedAt: Date;
  raw?: unknown;                    // vendor payload, for adapter-specific needs
}

// ---- Outbound: anything that can deliver a notification ----
interface NotificationChannel {
  id: string;                       // e.g. "slack-eng-team"
  send(notification: Notification): Promise<void>;
  supportsThreading?: boolean;
}

interface Notification {
  ticketId: string;
  title: string;
  body: string;
  priority: "low" | "normal" | "high" | "urgent";
  link: string;
  recipientHint?: string;           // channel/user, resolved by routing rules
}

// ---- Outbound: persistence ----
interface TicketRepository {
  save(ticket: Ticket): Promise<void>;
  findById(id: string): Promise<Ticket | null>;
  findByExternalRef(sourceId: string, externalId: string): Promise<Ticket | null>;
}

// ---- Outbound: identity/user resolution (also swappable: LDAP, Okta, static config) ----
interface UserDirectory {
  resolveAssignee(routingKey: string): Promise<User | null>;
}
```

Every adapter is just a class implementing one of these. Nothing in the
application layer imports `@slack/web-api` or `imap` directly — only the
adapter files do.

---

## 4. Event-Driven Core (so adapters never talk to each other)

Instead of "email adapter calls Slack adapter," everything flows through
domain events on an internal bus (in-process `EventEmitter` for a small
deployment, or Redis/NATS/Kafka/SQS for a distributed one — this itself is
swappable behind an `EventBus` port).

```typescript
interface EventBus {
  publish<T>(event: DomainEvent<T>): Promise<void>;
  subscribe<T>(eventType: string, handler: (event: DomainEvent<T>) => Promise<void>): void;
}

// Examples of domain events:
// "ticket.created", "ticket.assigned", "ticket.priority_changed", "ticket.sla_breached"
```

Flow for a new email → Slack notification:

1. `EmailAdapter` (IMAP or Gmail — doesn't matter which) receives a message →
   calls the `CreateTicketFromMessage` use case.
2. Use case creates a `Ticket` via `TicketRepository`, applies routing rules,
   publishes `ticket.created`.
3. A `NotificationDispatcher` use case is subscribed to `ticket.created`. It
   looks up **which channel(s)** should be notified (from config/routing
   rules) and calls `NotificationChannel.send()` on the resolved adapter(s).

The email adapter never knows Slack exists. The Slack adapter never knows
whether the ticket came from Gmail, IMAP, a web form, or an API call. You can
swap either side independently.

---

## 5. Plugin Registry & Config-Driven Wiring

This is what makes "change later" actually painless — no code changes, just
config + restart (or hot-reload if you want to go further).

```typescript
// registry.ts
const sourceAdapters: Record<string, (cfg: any) => MessageSource> = {
  "gmail": (cfg) => new GmailAdapter(cfg),
  "imap": (cfg) => new ImapAdapter(cfg),
  "outlook": (cfg) => new OutlookAdapter(cfg),
};

const channelAdapters: Record<string, (cfg: any) => NotificationChannel> = {
  "slack": (cfg) => new SlackAdapter(cfg),
  "telegram": (cfg) => new TelegramAdapter(cfg),
  "whatsapp": (cfg) => new WhatsAppAdapter(cfg),
};
```

```yaml
# config.yaml
sources:
  - id: support-inbox
    type: gmail
    config: { account: support@company.com, oauthCredsRef: gmail-creds }
  - id: sales-inbox
    type: imap
    config: { host: imap.example.com, user: sales@company.com }

channels:
  - id: eng-alerts
    type: slack
    config: { webhookRef: slack-eng-webhook }
  - id: oncall-urgent
    type: telegram
    config: { botTokenRef: tg-bot-token, chatId: "-100123" }

routing:
  - match: { source: sales-inbox }
    notify: [eng-alerts]
  - match: { priority: urgent }
    notify: [oncall-urgent, eng-alerts]
```

The **composition root** (`bootstrap.ts`) reads this config, looks up each
`type` in the registry, and instantiates it. To replace WhatsApp with
Telegram: change `type: whatsapp` → `type: telegram` in config, add
credentials, restart. To run three mailboxes at once: add three entries under
`sources`. Zero changes to domain or use-case code.

This is effectively the **Strategy pattern** (interchangeable algorithms) plus
a **Factory/Registry** (so the choice is data, not `if/else` in code), which
is the standard way to satisfy "interchangeable modules" requirements.

---

## 6. Suggested Project Structure

```
ticket-system/
├── src/
│   ├── domain/                  # pure business logic, no I/O
│   │   ├── ticket.ts
│   │   ├── sla-policy.ts
│   │   └── routing-rules.ts
│   ├── application/              # use cases, orchestration only
│   │   ├── create-ticket-from-message.ts
│   │   ├── notify-assignee.ts
│   │   └── close-ticket.ts
│   ├── ports/                    # interfaces only
│   │   ├── message-source.ts
│   │   ├── notification-channel.ts
│   │   ├── ticket-repository.ts
│   │   └── event-bus.ts
│   ├── adapters/
│   │   ├── sources/
│   │   │   ├── gmail-adapter.ts
│   │   │   ├── imap-adapter.ts
│   │   │   └── outlook-adapter.ts
│   │   ├── channels/
│   │   │   ├── slack-adapter.ts
│   │   │   ├── telegram-adapter.ts
│   │   │   └── whatsapp-adapter.ts
│   │   ├── persistence/
│   │   │   ├── postgres-ticket-repo.ts
│   │   │   └── in-memory-ticket-repo.ts   # useful for tests
│   │   └── event-bus/
│   │       ├── in-process-bus.ts
│   │       └── redis-bus.ts
│   ├── registry.ts               # maps config "type" strings → adapter constructors
│   └── bootstrap.ts               # composition root: reads config, wires everything
├── config/
│   └── config.yaml
└── tests/
    ├── domain/                   # fast, no mocks needed
    └── application/               # use cases tested against in-memory/fake adapters
```

---

## 7. Why This Solves Your Two Requirements

**"Change the notification platform later"** → `NotificationChannel` port +
registry. Adding WhatsApp support means writing one new adapter file
implementing `send()`; nothing else in the system changes. Running
Slack-now/Telegram-later is a config diff.

**"Interchangeable/combinable message sources"** → `MessageSource` port. One
Gmail inbox, or Gmail + IMAP + Outlook simultaneously, all normalize into the
same `InboundMessage` shape before hitting the domain. The domain has no idea
how many sources exist or what protocol they use.

**Bonus consequence:** this same pattern extends cleanly to anything else you
might swap later — ticket storage (Postgres → DynamoDB), auth (Okta → SAML),
even the event bus itself (in-process → Kafka when you outgrow a single
instance).

---

## 8. Testing Strategy This Enables

Because the domain and use cases depend only on interfaces, you test them with
fake/in-memory adapters and never touch real Slack/Gmail APIs:

```typescript
const fakeRepo = new InMemoryTicketRepository();
const fakeBus = new InProcessEventBus();
const useCase = new CreateTicketFromMessage(fakeRepo, fakeBus, routingRules);

await useCase.execute(sampleInboundMessage);
expect(await fakeRepo.findById(...)).toBeDefined();
```

Adapter-specific tests (does `SlackAdapter.send()` actually call the Slack API
correctly) live separately and only test the adapter, not the domain.

---

## 9. Suggested Tech Stack (opinionated, swap freely)

- **Language:** TypeScript/Node.js or Python — both have first-class SDKs for
  Slack, Telegram, WhatsApp Business API, Gmail API, and IMAP.
- **Event bus:** start with in-process `EventEmitter`; move to Redis Streams
  or NATS when you need multiple instances/workers.
- **Storage:** Postgres for tickets (relational, good for SLA queries);
  keep the `TicketRepository` interface so you could swap to another store
  later without touching use cases.
- **Config:** YAML + a secrets manager reference (Vault/SSM) rather than raw
  tokens in config, as shown in the example above.
- **Deployment:** each adapter type that needs a long-lived connection (IMAP
  IDLE, Telegram long-polling) can run as its own worker process, all
  publishing to the same event bus — this also means one flaky adapter can't
  take down the others.