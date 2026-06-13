from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("biodynamic_calendar_app:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
