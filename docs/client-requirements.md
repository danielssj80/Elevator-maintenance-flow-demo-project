---
description: Client-side prerequisites for full functionality — browser support and the text-to-speech voices the pre-visit voice briefing relies on.
alwaysApply: false
---

# Client-Side Requirements

Some features run entirely in the user's browser and depend on the **browser and operating system**, not on the server. This document lists those prerequisites and how to satisfy them.

---

## Browser

A modern evergreen browser (recent Chrome, Edge, Firefox, or Safari) is expected. The dashboard and unit detail views work without any special configuration.

---

## Text-to-speech voices (pre-visit voice briefing)

The pre-visit briefing is read aloud using the browser **Web Speech API** (`speechSynthesis`). The browser does **not** ship its own voices — it uses the **text-to-speech voices installed in the operating system**. Behaviour therefore depends on the device:

| Installed voices | Behaviour |
|---|---|
| An **English** voice (`en-*`) | The briefing is spoken with that English voice — correct pronunciation, including numbers (e.g. `0.83` → "zero point eight three"). **Recommended.** |
| Only **non-English** voices | The briefing is spoken with the device's default voice (audible, but with a non-English accent and local number reading). The UI shows a note: *"No English voice installed — using the device default voice."* |
| **No** voices installed | No audio is played. The briefing **text is always shown**, and the UI shows: *"No text-to-speech voice is available on this device — showing text only."* |

The briefing text is always English, so an **English voice is recommended** for the best experience.

### Installing an English voice

- **Windows**: Settings → *Time & language* → *Speech* → *Add voices* → install *English (United States)*. Restart the browser.
- **macOS**: System Settings → *Accessibility* → *Spoken Content* → *System voice* → *Manage Voices…* → download an English voice (e.g. *Samantha*). Restart the browser.
- **Android (Chrome)**: Settings → *Accessibility* → *Text-to-speech output* → Google engine → *Install voice data* → download English (US).
- **iOS / iPadOS (Safari)**: Settings → *Accessibility* → *Spoken Content* → *Voices* → *English* → download a voice.
- **Linux (Chrome/Chromium)**: usually no voices by default. Install a speech engine, e.g. `sudo apt install speech-dispatcher espeak-ng`, then restart the browser. (`espeak-ng` voices sound robotic but work.)

After installing a voice, restart the browser so it is picked up.

> Note: headless/CI browsers typically expose **zero** voices, so automated tests exercise the text-only path. This is expected.
