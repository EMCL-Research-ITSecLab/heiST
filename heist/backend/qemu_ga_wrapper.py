import base64
import json
import logging
import os
import socket
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

__all__ = [
    "GuestAgent",
    "GuestAgentError",
    "GATimeoutError",
    "GANotRunningError",
    "GACommandError",
    "GASocketNotFoundError",
    "ExecResult",
]

logger = logging.getLogger(__name__)

_SOCKET_DIR = Path("/var/run/qemu-server")
_DEFAULT_CONNECT_TIMEOUT: float = 5.0
_DEFAULT_RECV_TIMEOUT: float = 10.0
_DEFAULT_EXEC_TIMEOUT: float = 30.0
_RECV_CHUNK: int = 4096
_GREETING_TIMEOUT: float = 3.0
_DEFAULT_SOCKET_WAIT_TIMEOUT: float = 120.0

class GuestAgentError(Exception):
    """Base exception for all qemu-ga errors."""


class GASocketNotFoundError(GuestAgentError):
    """Socket file does not exist or is not accessible."""


class GANotRunningError(GuestAgentError):
    """The guest agent inside the VM is not responding."""


class GATimeoutError(GuestAgentError):
    """A socket or command operation exceeded the allowed timeout."""


class GACommandError(GuestAgentError):
    """The guest agent returned an error response for a command."""

    def __init__(self, klass: str, desc: str) -> None:
        super().__init__(f"[{klass}] {desc}")
        self.klass = klass
        self.desc = desc


@dataclass(slots=True)
class ExecResult:
    """Result of a guest-exec call."""

    pid: int
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    exited: bool = False

    def __bool__(self) -> bool:
        return self.exit_code == 0


class _QEMUGATransport:
    """JSON transport over AF_UNIX socket."""

    def __init__(
        self,
        socket_path: Path,
        connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
        recv_timeout: float = _DEFAULT_RECV_TIMEOUT,
    ) -> None:
        self._path = socket_path
        self._connect_timeout = connect_timeout
        self._recv_timeout = recv_timeout
        self._sock: Optional[socket.socket] = None
        self._buf = b""


    def wait_for_socket(
        self,
        timeout: float = 120.0,
        poll_interval: float = 1.0,
    ) -> None:
        """Block until the socket file appears and is accessible, or raise."""
        deadline = time.monotonic() + timeout
        while True:
            if self._path.exists() and os.access(self._path, os.R_OK | os.W_OK):
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GATimeoutError(
                    f"Socket {self._path} did not appear within {timeout}s "
                    f"(is the VM booting and qemu-ga installed?)"
                )
            logger.debug(
                "Waiting for socket %s (%.0fs remaining)…",
                self._path,
                remaining,
            )
            time.sleep(min(poll_interval, remaining))

    def connect(self, *, wait_timeout: Optional[float] = None) -> None:
        """Connect to the socket, optionally waiting for it to appear first."""
        import errno as _errno

        if wait_timeout is not None:
            self.wait_for_socket(timeout=wait_timeout)

        if not self._path.exists():
            raise GASocketNotFoundError(
                f"QEMU-GA socket not found: {self._path}  "
                f"(is the VM running and qemu-ga installed?)"
            )
        if not os.access(self._path, os.R_OK | os.W_OK):
            raise GASocketNotFoundError(
                f"No r/w permission on {self._path}  (run as root)"
            )

        deadline = time.monotonic() + self._connect_timeout
        last_exc: Optional[OSError] = None
        while time.monotonic() < deadline:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.setblocking(True)
            try:
                sock.connect(str(self._path))
                sock.settimeout(self._recv_timeout)
                self._sock = sock
                self._buf = b""
                self._flush_greeting()
                logger.debug("Connected to %s", self._path)
                return
            except FileNotFoundError:
                sock.close()
                raise GASocketNotFoundError(f"Socket vanished: {self._path}")
            except OSError as exc:
                sock.close()
                if exc.errno == _errno.EAGAIN:
                    last_exc = exc
                    logger.debug(
                        "EAGAIN on connect to %s, retrying…", self._path
                    )
                    time.sleep(0.2)
                    continue
                raise GANotRunningError(
                    f"Cannot connect to {self._path}: {exc}"
                ) from exc

        raise GANotRunningError(
            f"Cannot connect to {self._path} after retrying for "
            f"{self._connect_timeout}s: {last_exc}"
        ) from last_exc

    def _drain(self, timeout: float = 2.0) -> None:
        """Read and discard everything pending in the socket buffer."""
        if self._sock is None:
            return
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                self._sock.settimeout(min(0.1, deadline - time.monotonic()))
                chunk = self._sock.recv(_RECV_CHUNK)
                if not chunk:
                    break
        except OSError:
            pass

    def close(self) -> None:
        if self._sock is not None:
            self._drain()
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            self._buf = b""

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def _flush_greeting(self) -> None:
        """Discard optional greeting line emitted on first connect."""
        assert self._sock is not None
        deadline = time.monotonic() + _GREETING_TIMEOUT
        try:
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._sock.settimeout(min(remaining, _GREETING_TIMEOUT))
                try:
                    chunk = self._sock.recv(_RECV_CHUNK)
                except socket.timeout:
                    logger.debug("No greeting received from %s. Continuing.", self._path)
                    return
                if not chunk:
                    return
                self._buf += chunk
                nl = self._buf.find(b"\n")
                if nl != -1:
                    self._buf = self._buf[nl + 1:]
                    return
        except OSError:
            pass

    def _read_line(self, timeout: Optional[float] = None) -> bytes:
        assert self._sock is not None
        effective = timeout if timeout is not None else self._recv_timeout
        deadline = time.monotonic() + effective

        while True:
            nl = self._buf.find(b"\n")
            if nl != -1:
                line, self._buf = self._buf[:nl], self._buf[nl + 1:]
                return line

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close()  # socket is dirty -> force reconnect on next call
                raise GATimeoutError(
                    f"Timed out waiting for response from {self._path} "
                    f"(timeout={effective}s)"
                )

            self._sock.settimeout(min(remaining, self._recv_timeout))
            try:
                chunk = self._sock.recv(_RECV_CHUNK)
            except socket.timeout:
                self.close()  # socket is dirty -> force reconnect on next call
                raise GATimeoutError(
                    f"Timed out waiting for response from {self._path}"
                ) from None
            except OSError as exc:
                self.close()
                raise GANotRunningError(
                    f"Socket error reading from {self._path}: {exc}"
                ) from exc

            if not chunk:
                self.close()
                raise GANotRunningError(f"Remote end closed socket: {self._path}")

            self._buf += chunk


    def call(
        self,
        command: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        if not self.connected:
            raise GANotRunningError("Transport is not connected.")

        payload: Dict[str, Any] = {"execute": command}
        if arguments:
            payload["arguments"] = arguments

        raw = json.dumps(payload, separators=(",", ":")) + "\n"
        logger.debug("-> %s", raw.rstrip())

        assert self._sock is not None
        try:
            self._sock.sendall(raw.encode())
        except OSError as exc:
            self.close()
            raise GANotRunningError(f"Failed to send '{command}': {exc}") from exc

        line = self._read_line(timeout=timeout)
        logger.debug("<- %s", line.decode(errors="replace"))

        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GuestAgentError(f"Non-JSON from qemu-ga: {line[:200]!r}") from exc

        if "error" in response:
            err = response["error"]
            raise GACommandError(
                klass=err.get("class", "Unknown"),
                desc=err.get("desc", str(err)),
            )

        return response.get("return")


def _wrap_for_windows(command: str, args: List[str]) -> List[str]:
    """Wrap a command in ``cmd.exe /c start /wait /MIN`` for Windows guests.

    The shipped PowerShell on Windows Server 2008 R2 crashes with a Win32Exception when
    launched in a QGA session because there is no console window handle.
    Wrapping in ``start /wait /MIN`` provides a minimised window handle and
    ``-NonInteractive`` suppresses console interaction.
    """

    def _quote(token: str) -> str:
        if " " in token or '"' in token:
            return '"' + token.replace('"', '\\"') + '"'
        return token

    is_ps = command.lower().endswith("powershell.exe")
    if is_ps and "-NonInteractive" not in args:
        args = ["-NonInteractive"] + list(args)

    inner = " ".join(_quote(t) for t in [command] + list(args))
    return ["cmd.exe", "/c", f"start /wait /MIN {inner}"]


class GuestAgent:
    """QEMU Guest Agent client for a single Proxmox VM."""

    def __init__(
        self,
        vmid: int,
        windows: bool = False,
        connect_timeout: float = _DEFAULT_CONNECT_TIMEOUT,
        recv_timeout: float = _DEFAULT_RECV_TIMEOUT,
        auto_reconnect: bool = True,
        socket_wait_timeout: Optional[float] = _DEFAULT_SOCKET_WAIT_TIMEOUT,
    ) -> None:
        self.vmid = vmid
        self.windows = windows
        self._auto_reconnect = auto_reconnect
        self._socket_wait_timeout = socket_wait_timeout
        self._lock = threading.Lock()
        self._transport = _QEMUGATransport(
            _resolve_socket_path(vmid),
            connect_timeout=connect_timeout,
            recv_timeout=recv_timeout,
        )


    def __enter__(self) -> "GuestAgent":
        self._ensure_connected()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


    def _ensure_connected(self) -> None:
        if not self._transport.connected:
            self._transport.connect(wait_timeout=self._socket_wait_timeout)

    def _call(
        self,
        command: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        with self._lock:
            self._ensure_connected()
            try:
                return self._transport.call(command, arguments, timeout=timeout)
            except (GANotRunningError, GATimeoutError):
                if self._auto_reconnect:
                    logger.warning(
                        "VM %s: connection lost or timed out. Reconnecting...", self.vmid
                    )
                    self._transport.close()
                    self._transport.connect()
                    return self._transport.call(command, arguments, timeout=timeout)
                raise

    def close(self) -> None:
        with self._lock:
            self._transport.close()


    def ping(self) -> bool:
        """Return True if qemu-ga is alive.  Never raises."""
        try:
            self._call("guest-ping")
            return True
        except GuestAgentError as exc:
            logger.debug("ping failed for VM %s: %s", self.vmid, exc)
            return False


    def exec(
        self,
        command: Union[str, Sequence[str]],
        *,
        capture_output: bool = True,
        input_data: Optional[bytes] = None,
        timeout: float = _DEFAULT_EXEC_TIMEOUT,
        poll_interval: float = 0.25,
        env: Optional[Dict[str, str]] = None,
    ) -> ExecResult:
        """Execute a command inside the guest and wait for it to finish."""
        if isinstance(command, str):
            argv: List[str] = ["/bin/sh", "-c", command]
        else:
            argv = list(command)

        if self.windows:
            return self._exec_windows(argv, timeout=timeout)
        return self._exec_socket(
            argv,
            capture_output=capture_output,
            input_data=input_data,
            timeout=timeout,
            poll_interval=poll_interval,
            env=env,
        )

    def _exec_socket(
        self,
        argv: List[str],
        capture_output: bool,
        input_data: Optional[bytes],
        timeout: float,
        poll_interval: float,
        env: Optional[Dict[str, str]],
    ) -> ExecResult:
        args: Dict[str, Any] = {
            "path": argv[0],
            "arg": argv[1:],
            "capture-output": capture_output,
        }
        if input_data is not None:
            args["input-data"] = base64.b64encode(input_data).decode()
        if env:
            args["env"] = [f"{k}={v}" for k, v in env.items()]

        result = self._call("guest-exec", args)
        pid: int = result["pid"]

        deadline = time.monotonic() + timeout
        while True:
            status = self._call("guest-exec-status", {"pid": pid})
            if status.get("exited"):
                return ExecResult(
                    pid=pid,
                    exit_code=status.get("exitcode", -1),
                    stdout=_b64decode_str(status.get("out-data", "")),
                    stderr=_b64decode_str(status.get("err-data", "")),
                    exited=True,
                )
            if time.monotonic() > deadline:
                raise GATimeoutError(
                    f"VM {self.vmid}: {argv!r} did not exit within "
                    f"{timeout}s (pid={pid})"
                )
            time.sleep(poll_interval)

    def _exec_windows(self, argv: List[str], timeout: float) -> ExecResult:
        """Execute a command on a Windows guest.

        Attempts direct ``guest-exec`` first.  If the process is PowerShell
        and returns no output with a non-zero exit code, or hangs and never exits within the timeout, the call is retried
        wrapped in ``cmd.exe /c start /wait /MIN`` to supply a window handle.
        """
        is_ps = argv[0].lower().endswith("powershell.exe")
        command, args = argv[0], argv[1:]

        try:
            result = self._exec_socket(
                argv,
                capture_output=True,
                input_data=None,
                timeout=timeout,
                poll_interval=0.5,
                env=None,
            )
            if result.exit_code == 0:
                return result
            if is_ps and not result.stdout and not result.stderr:
                pass
            else:
                return result
        except GACommandError:
            if not is_ps:
                raise
        except GATimeoutError:
            if not is_ps:
                raise
            logger.warning(
                "PowerShell exec hung, retrying wrapped: %r",
                argv,
            )

        wrapped = _wrap_for_windows(command, args)
        return self._exec_socket(
            wrapped,
            capture_output=True,
            input_data=None,
            timeout=timeout,
            poll_interval=0.5,
            env=None,
        )

    def read_file(self, guest_path: str, *, chunk_size: int = 65536) -> bytes:
        """Read a file from inside the guest and return its contents."""
        handle: int = self._call(
            "guest-file-open", {"path": guest_path, "mode": "r"}
        )
        buf = bytearray()
        try:
            while True:
                chunk = self._call(
                    "guest-file-read",
                    {"handle": handle, "count": chunk_size},
                )
                if chunk.get("buf-b64"):
                    buf.extend(base64.b64decode(chunk["buf-b64"]))
                if chunk.get("eof"):
                    break
        finally:
            try:
                self._call("guest-file-close", {"handle": handle})
            except GuestAgentError:
                pass
        return bytes(buf)


    def write_file(
        self,
        guest_path: str,
        data: Union[bytes, str],
        *,
        mode: str = "w",
        unix_mode: Optional[int] = None,
    ) -> None:
        """Write data to guest_path inside the guest."""
        raw = data.encode("utf-8") if isinstance(data, str) else data
        handle: int = self._call(
            "guest-file-open", {"path": guest_path, "mode": mode}
        )
        try:
            self._call(
                "guest-file-write",
                {"handle": handle, "buf-b64": base64.b64encode(raw).decode()},
            )
            self._call("guest-file-flush", {"handle": handle})
        finally:
            try:
                self._call("guest-file-close", {"handle": handle})
            except GuestAgentError:
                pass

        if unix_mode is not None:
            if self.windows:
                logger.debug(
                    "unix_mode=%o requested for %s but VM %s is Windows; ignoring",
                    unix_mode, guest_path, self.vmid,
                )
            else:
                self.exec(
                    ["chmod", format(unix_mode, "o"), guest_path],
                    capture_output=False,
                    timeout=10,
                )

    def write_local_file(
        self,
        local_path: Union[str, Path],
        guest_path: str,
        *,
        preserve_mode: bool = True,
    ) -> None:
        """Read a local file and write it to guest_path inside the guest,
        preserving the local file's Unix permission bits by default
        (Linux guests only -- ignored for Windows guests).
        """
        local_path = Path(local_path)
        data = local_path.read_bytes()
        unix_mode = None
        if preserve_mode and not self.windows:
            unix_mode = stat.S_IMODE(local_path.stat().st_mode)
        self.write_file(guest_path, data, unix_mode=unix_mode)


def _resolve_socket_path(vmid: int) -> Path:
    if not _SOCKET_DIR.is_dir():
        raise GASocketNotFoundError(
            f"Socket directory {_SOCKET_DIR} not found"
        )
    return _SOCKET_DIR / f"{vmid}.qga"


def _b64decode_str(value: str, encoding: str = "utf-8") -> str:
    if not value:
        return ""
    try:
        return base64.b64decode(value).decode(encoding, errors="replace")
    except Exception:
        return ""