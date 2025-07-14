
<h1 align="center">Drop The Handkerchief - A Duel-Based Game Bot</h1>

<p align="center">
A strategic number duel game for Discord built with Python.<br>
Challenge friends, play in DMs, and track your stats across guilds.
</p>

---

## 📌 Features

- Duel-based gameplay using the classic "Drop the Handkerchief" concept
- Slash commands: `/duel`, `/accept`, `/decline`, `/drop`, `/stats`
- DM-based number entry with timeout handling
- Real-time point tracking and stat recording (wins/losses/ties)
- Error-safe duel cancellation and cleanup
- JSON-based persistent score saving per server

---

## ⚙️ How It Works

- One user challenges another using `/duel`.
- Both users are assigned roles: **Dropper** or **Checker**.
- Each privately chooses a number from 1 to 60 via DM.
- The winner is determined by comparing numbers:
  - Checker wins if their number is higher.
  - Dropper wins if their number is higher.
  - A tie if both choose the same number.
- Points are added/subtracted based on outcomes and stored in `scores.json`.

---

## 🖥 Requirements

- Python 3.8+
- Discord Bot Token
- Required Python packages:
  - `discord.py`
  - `python-dotenv`
