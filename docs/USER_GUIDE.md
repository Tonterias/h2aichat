# User Guide

A quick guide to using H2AI Chat: moderating a debate between several AIs.

## 1. Roles

The system has two kinds of participants:

| Role | Type | Description |
|:---|:---|:---|
| **Moderator** | `human` | Orchestrates the conversation. Starts topics, can step in at any time, and stops the orchestration. |
| **AI agent** | `bot` | A model with a role (for example: creative, strategist, analyst). Runs in the cloud or on a local model server. |

Agents take turns in a fixed order within each round. The moderator can intervene whenever they start a message.

## 2. Start a conversation

Make sure the server is running (`http://localhost:8000`), then:

1. Open `http://localhost:8000` in your browser.
2. Type a message in the text field at the bottom bar.
3. Press `Enter` or click the send button.

The system will register the participants (on first run), give the turn to the moderator, and start the orchestration by rounds (3 by default). In each round, every bot reads its messages, queries its model, and replies to the next participant.

## 3. Stop the conversation

The red square button in the bottom bar:

- **While orchestrating:** it pulses red. Clicking sends a stop signal that cleanly ends the current round. Bots that had already replied keep their messages.
- **When idle:** clicking clears the turn queue and resets the state to `idle`.

## 4. Send messages during orchestration

While the system is orchestrating, the text field stays enabled. Type a message and press `Enter`: it is **injected directly** into the active conversation without interrupting the orchestration. The bots will read it on their next round.

## 5. Threads

Use the thread selector in the **Chat** header to separate topics. The default thread is `general`. To create a thread on the fly, type `#thread_name: your message`. Each thread keeps its own message history.

## 6. The dashboard

Click the **Dashboard** tab for a session overview:

- **Session summary:** total turns, average time per turn, participants, and moderator interventions.
- **Turn sequence:** a horizontal timeline of colored pills showing the chronological order of turns; each participant has its own color and logo.
- **Activity by agent:** per-participant cards with turns taken, average response time, and errors.
- **Recent activity:** the latest messages, with timestamp, participant, and a status badge.

## 7. Interface tabs

- **Chat:** all messages in the selected thread, in chronological order. Moderator messages are centered; agents alternate left/right for easy reading. Each header shows the model's logo, the sender, and the recipient.
- **Participants:** click any participant in the left sidebar to see only that participant's mailbox — useful to inspect what each bot received before replying.
- **Dashboard:** described above.

## 8. Common workflows

**Start a new topic:** type your opening message (optionally with a `#new_thread` prefix) and press `Enter`; watch the bots reply in sequence.

**Intervene mid-conversation:** while orchestrating, type your message and press `Enter`; it is injected without stopping the debate.

**Stop and restart:** click the red square; the system returns to idle; type a new message to start a new orchestration.

## 9. Moderator pause

When a bot asks you a direct question, the system can pause the orchestration for a few seconds so you can reply. Configure it in Settings → Moderator pause (seconds). A value of 0 disables it.

## 10. Troubleshooting

| Problem | Likely cause | Fix |
|:---|:---|:---|
| Frontend won't load | Server not started | Start the server |
| Bots don't respond | API key not configured | Check `auth.json` or `OPENCODE_API_KEY`, or your local model server |
| Bot timeout | The model took too long | The system skips that bot and injects a fallback message |
| Inconsistent state | Orphan turn lock | Click the red square (hard reset) |
