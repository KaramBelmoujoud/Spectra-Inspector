# Security policy

## Supported versions

Spectra Inspector is young; security fixes go into the latest release only.

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Report them privately through GitHub instead: on the repository's **Security** tab, choose **Report a vulnerability** (GitHub private vulnerability reporting). Only the maintainers can see the report.

Please include the version, what you did, what happened, and how it can be reproduced. You'll get an acknowledgement within a week, and we'll keep you informed until the issue is fixed and released. We're happy to credit you in the release notes.

## What Spectra does on your machine

Spectra is a desktop inspection tool, so it is good to know what it can access:

* **It reads and drives your desktop.** Through UI Automation, MSAA, Win32 and the Java Access Bridge it reads the UI of applications you inspect. The **Try it** actions (Click, Type text, Set value, Invoke and so on) and the scripting API act on those applications only when you ask them to.
* **Low-level mouse hook, only while picking.** After you press F3, Spectra installs a system-wide mouse hook so that the click that captures an element is not passed to the application. The hook is removed as soon as you capture or cancel (Esc, right-click) or close Spectra. It does not record or store input.
* **Browser DevTools connections.** To inspect web pages, Spectra connects to a browser's remote-debugging port (by default only on `127.0.0.1`). Anything that can reach that port can control the browser, so only enable remote debugging on machines and networks you trust, and use the separate profile Spectra creates rather than your everyday profile.
* **Logs.** Errors are written to `%LOCALAPPDATA%\Spectra\spectra.log` on your machine. Nothing is sent anywhere; Spectra has no telemetry and makes no network connections other than to the browser debugging ports you connect to.
