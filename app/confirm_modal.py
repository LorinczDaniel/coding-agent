from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "approve", "Yes", priority=True),
        Binding("n", "deny", "No", priority=True),
        Binding("escape", "deny", "No", priority=True),
    ]

    CSS = """
    ConfirmModal {
        align: center middle;
    }

    #modal-box {
        width: 70;
        max-width: 90%;
        padding: 1 2;
        background: $panel;
        border: thick $warning;
    }

    #modal-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    #modal-reason {
        color: $text-muted;
        margin-bottom: 1;
    }

    #modal-body {
        color: $text;
        margin-bottom: 1;
    }

    #modal-buttons {
        height: 3;
        align-horizontal: center;
    }

    #modal-buttons Button {
        margin: 0 1;
        min-width: 14;
    }
    """

    def __init__(self, title: str, reason: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._reason = reason
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Label(f"⚠ Confirm: {self._title}", id="modal-title")
            yield Label(self._reason, id="modal-reason")
            yield Static(self._body, id="modal-body")
            with Horizontal(id="modal-buttons"):
                yield Button("Yes (y)", id="yes-btn", variant="warning")
                yield Button("No (n)", id="no-btn", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes-btn")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)
