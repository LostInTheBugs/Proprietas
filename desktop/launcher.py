"""Proprietas Desktop — lance le serveur local puis ouvre la fenêtre native.

Double-clic sur Proprietas.exe (Windows) ou Proprietas.app (macOS) : le
backend (uvicorn) démarre sur un port local libre (127.0.0.1), la fenêtre
s'ouvre sur l'application. Les données vivent dans « data/ », à côté de
l'application — sauvegarder = copier ce dossier, rien ne sort de la machine.

Variables d'environnement :
  PROPRIETAS_NO_WINDOW=1  → mode sans fenêtre (serveur seul ; tests, CI)
  PROPRIETAS_PORT=<port>  → port fixe (défaut : port libre automatique)
"""

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path


def base_dir() -> Path:
    """Dossier de travail : à côté de l'application (bundle) ou racine du dépôt (dev).

    macOS : le binaire vit dans « Proprietas.app/Contents/MacOS/ » — les données
    vont À CÔTÉ du .app (jamais dedans), comme sur Windows à côté de l'exe.
    """
    if getattr(sys, "frozen", False):  # exécutable PyInstaller
        exe = Path(sys.executable).resolve()
        if sys.platform == "darwin":
            for parent in exe.parents:
                if parent.suffix == ".app":
                    return parent.parent
        return exe.parent
    return Path(__file__).resolve().parent.parent


def data_dir(base: Path) -> Path:
    """Dossier « data » : à côté de l'application si l'emplacement est inscriptible.

    Repli macOS (emplacement protégé — lecture seule, translocation Gatekeeper) :
    ~/Library/Application Support/Proprietas/data.
    """
    cand = base / "data"
    try:
        cand.mkdir(parents=True, exist_ok=True)
        probe = cand / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return cand
    except OSError:
        if sys.platform == "darwin":
            alt = Path.home() / "Library" / "Application Support" / "Proprietas" / "data"
            alt.mkdir(parents=True, exist_ok=True)
            return alt
        raise


def resource_dir() -> Path:
    """Ressources embarquées (frontend_dist, alembic) : _MEIPASS ou dépôt (dev)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_server(port: int, tries: int = 300) -> bool:
    for _ in range(tries):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def screen_size() -> tuple:
    """Taille de l'écran (Windows / macOS) pour ne pas ouvrir plus grand que lui."""
    if sys.platform == "darwin":
        try:  # API pywebview ; repli AppKit ; repli taille raisonnable
            import webview

            s = webview.screens[0]
            return int(s.width), int(s.height)
        except Exception:
            try:
                from AppKit import NSScreen

                f = NSScreen.mainScreen().frame()
                return int(f.size.width), int(f.size.height)
            except Exception:
                return 1280, 800
    try:
        import ctypes

        u = ctypes.windll.user32
        return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
    except Exception:
        return 1280, 800


def _machine_info() -> list:
    """Diagnostic machine (Windows) : .NET, runtime WebView2, versions."""
    import platform as _p

    lines = [
        "Proprietas Desktop - journal de démarrage",
        time.strftime("%Y-%m-%d %H:%M:%S"),
        f"python: {sys.version}",
        f"platform: {_p.platform()}",
        f"frozen: {getattr(sys, 'frozen', False)}",
        f"executable: {sys.executable}",
    ]
    try:
        import webview as _wv

        lines.append(f"pywebview: {getattr(_wv, '__version__', '?')}")
    except Exception as e:
        lines.append(f"import webview: ECHEC ({e!r})")
    try:
        import winreg

        try:
            k = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
            )
            lines.append(f"netfx Release: {winreg.QueryValueEx(k, 'Release')[0]}")
        except Exception as e:
            lines.append(f"netfx: indetectable ({e})")
        for key, name in (
            ("{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "WebView2 Runtime"),
            ("{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}", "WebView2 Beta"),
            ("{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}", "WebView2 Dev"),
            ("{65C35B14-6C1D-4122-AC46-7148CC9D6497}", "WebView2 Canary"),
        ):
            found = "absent"
            for hive, path in (
                (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{key}"),
                (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{key}"),
                (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{key}"),
            ):
                try:
                    kk = winreg.OpenKey(hive, path)
                    found = str(winreg.QueryValueEx(kk, "pv")[0])
                    break
                except Exception:
                    pass
            lines.append(f"{name}: {found}")
    except Exception as e:
        lines.append(f"winreg indisponible ({e})")
    return lines


def _write_desktop_log(blocks: list) -> None:
    """Écrit desktop.log à côté de l'exécutable (diagnostic fenêtre native)."""
    try:
        txt = "\n".join(_machine_info() + [""] + blocks) + "\n"
        (base_dir() / "desktop.log").write_text(txt, encoding="utf-8")
    except Exception:
        pass


def _warn_user(base: Path) -> None:
    """Avertit l'utilisateur que la fenêtre native a échoué (best effort)."""
    msg = (
        "La fenêtre native de Proprietas n'a pas pu s'ouvrir.\n"
        "Un journal de diagnostic a été écrit :\n"
        f"{base / 'desktop.log'}\n\n"
        "L'application s'ouvre dans votre navigateur.\n"
        "Merci d'envoyer ce journal au développeur."
    )
    try:
        if sys.platform == "darwin":
            import subprocess

            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'display dialog "{}" buttons {{"OK"}} with title "Proprietas"'
                    ' with icon caution'.format(msg.replace('"', "'").replace("\n", " ")),
                ],
                check=False,
            )
            return
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, msg, "Proprietas", 0x30)
    except Exception:
        pass


def prepare_env(base: Path, res: Path) -> None:
    """Configuration du serveur embarqué : SQLite + uploads dans data/."""
    data = data_dir(base)
    os.environ.setdefault(
        "COPRO_DATABASE_URL", "sqlite:///" + (data / "proprietas.db").as_posix()
    )
    os.environ.setdefault("COPRO_UPLOAD_DIR", str(data / "uploads"))
    os.environ.setdefault("COPRO_FRONTEND_DIST", str(res / "frontend_dist"))
    # Instance mono-poste (pas d'accès internet) : pas de 2FA obligatoire — elle
    # reste activable à la main dans la page Sécurité.
    os.environ.setdefault("COPRO_TOTP_DEFAULT_POLICY", "off")
    # Clé secrète persistée dans data/ : les sessions survivent au redémarrage.
    if "COPRO_SECRET_KEY" not in os.environ:
        keyfile = data / "secret.key"
        if keyfile.is_file():
            key = keyfile.read_text(encoding="utf-8").strip()
        else:
            key = os.urandom(32).hex()
            keyfile.write_text(key + "\n", encoding="utf-8")
        os.environ["COPRO_SECRET_KEY"] = key


def run_migrations(res: Path) -> None:
    """`alembic upgrade head` embarqué — crée/met à jour le schéma SQLite."""
    from alembic import command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(res / "alembic.ini"))
    cfg.set_main_option("script_location", str(res / "alembic"))
    command.upgrade(cfg, "head")


class DesktopApi:
    """API JS → Python exposée à la page (window.pywebview.api.*).

    La WebView Windows n'exécute pas les téléchargements des liens vers
    l'API (exports PDF/CSV du serveur local) : le front intercepte ces clics
    et passe par « Enregistrer sous » natif (voir frontend/src/desktop.ts).
    """

    def save_file(self, filename: str, content: str, binary: bool = False, path=None) -> dict:
        import base64

        if not path:
            import webview

            win = webview.windows[0] if webview.windows else None
            if win is None:
                return {"ok": False, "error": "no-window"}
            chosen = win.create_file_dialog(webview.SAVE_DIALOG, save_filename=filename)
            if not chosen:
                return {"ok": False, "cancelled": True}
            path = chosen[0] if isinstance(chosen, (list, tuple)) else chosen
        target = Path(str(path))
        if binary:
            target.write_bytes(base64.b64decode(content))
        else:
            target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(path)}


def main() -> None:
    # Binaire fenêtré (console=False) : stdout/stderr valent None sous Windows,
    # ce qui fait planter la configuration des logs d'uvicorn (isatty sur None).
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    base = base_dir()
    res = resource_dir()
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(base / "backend"))  # dev : rendre « app » importable

    prepare_env(base, res)
    run_migrations(res)

    import uvicorn

    from app.main import app

    port = int(os.environ.get("PROPRIETAS_PORT") or 0) or free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    wait_server(port)
    # URL du serveur local (diagnostic & CI ; retirée du zip livré)
    try:
        (base / "url.txt").write_text(url + "\n", encoding="utf-8")
    except Exception:
        pass

    if os.environ.get("PROPRIETAS_NO_WINDOW") == "1":
        # mode headless (tests/CI) : stdout peut être absent (binaire windowed)
        try:
            print(url, flush=True)
        except Exception:
            pass
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return

    def _open_window() -> None:
        import webview  # fenêtre native (WebView2 sous Windows, WKWebView sous macOS)

        sw, sh = screen_size()
        w = min(1280, max(960, sw - 80))
        h = min(880, max(640, sh - 120))
        webview.create_window(
            "Proprietas",
            url,
            width=w,
            height=h,
            min_size=(900, 600),
            js_api=DesktopApi(),
        )
        # Le callback de start() s'exécute une fois la fenêtre affichée :
        # preuve d'ouverture consignée dans desktop.log (support & CI).
        webview.start(lambda: _write_desktop_log([f"fenêtre native ouverte — {url}"]))

    try:
        _open_window()
        return
    except Exception:
        import traceback

        first = traceback.format_exc()
        # Tentative 2 : état webview neuf (l'init WebView2/CLR peut échouer au
        # premier essai sur certaines machines) — journalisée dans les 2 cas.
        try:
            for m in [k for k in list(sys.modules) if k == "webview" or k.startswith("webview.")]:
                del sys.modules[m]
            _open_window()
            _write_desktop_log(["tentative 1 (traceback) :", first, "", "tentative 2 : OK"])
            return
        except Exception:
            second = traceback.format_exc()
        _write_desktop_log(
            ["tentative 1 (traceback) :", first, "", "tentative 2 (traceback) :", second]
        )
        _warn_user(base)
        import webbrowser

        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:  # binaire fenêtré : consigner le crash dans error.log
        import traceback

        try:
            (base_dir() / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        raise
