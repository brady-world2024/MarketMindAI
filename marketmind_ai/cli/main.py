from __future__ import annotations

from datetime import datetime
from typing import Optional

import typer

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency path
    load_dotenv = None

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from ..graph.request import AnalysisRequest
from ..web.app import run as run_web_app
from .announcements import display_announcements, fetch_announcements
from .config import CLI_DESCRIPTION, CLI_PROG, DEFAULT_ANALYSIS_DATE, DEFAULT_CLI_ANALYSTS, DEFAULT_HOST, DEFAULT_PORT
from .models import AnalyzeOptions, ResolveOptions, RunStatistics, ServeOptions, ValidateProviderOptions
from .stats_handler import StatsCallbackHandler
from .utils import (
    PromptAborted,
    build_analysis_request,
    build_interactive_analyze_options,
    dump_json,
    format_run_statistics,
    resolve_storage_root,
    workflow_from_storage_root,
)


if load_dotenv is not None:  # pragma: no cover - exercised only when dependency is present
    load_dotenv()
    load_dotenv(".env.enterprise", override=False)

console = Console()
app = typer.Typer(name=CLI_PROG, help=CLI_DESCRIPTION, add_completion=True)


def _display_announcements() -> None:
    display_announcements(fetch_announcements())


def _status_style(status: str) -> str:
    normalized = str(status or "").lower()
    if normalized == "completed":
        return "green"
    if normalized in {"running", "active"}:
        return "cyan"
    if normalized in {"error", "failed"}:
        return "red"
    return "yellow"


def _clip(text: str, limit: int = 220) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _completion(snapshot) -> tuple[int, int]:
    total = len(snapshot.agents)
    completed = sum(1 for agent in snapshot.agents if str(agent.status).lower() == "completed")
    return completed, total


def _render_overview(snapshot, stats: RunStatistics):
    completed, total = _completion(snapshot)
    percent = int((completed / total) * 100) if total else 0

    status = Table.grid(expand=True)
    status.add_column(justify="left", ratio=1)
    status.add_column(justify="left", ratio=2)
    status.add_row("Status", f"[{_status_style(snapshot.status)}]{snapshot.status}[/]")
    status.add_row("Ticker", str(snapshot.ticker))
    status.add_row("Date", str(snapshot.analysis_date))
    status.add_row("Provider", str(snapshot.provider))
    status.add_row("Models", f"{snapshot.quick_model} / {snapshot.deep_model}")
    status.add_row("Current Agent", str(snapshot.current_agent or "-"))
    status.add_row("Signal", str(snapshot.final_signal or "-"))
    status.add_row("Progress", f"{completed}/{total} agents")

    progress = Table.grid(expand=True)
    progress.add_column(ratio=3)
    progress.add_column(justify="right", ratio=1)
    progress.add_row(ProgressBar(total=100, completed=percent), f"{percent}%")
    return Panel(Group(status, Text(""), progress), title="Run Overview", border_style="cyan")


def _render_agents(snapshot):
    completed, total = _completion(snapshot)

    agents = Table(title="Agents", expand=True)
    agents.add_column("Role", ratio=3)
    agents.add_column("Status", ratio=1)
    for agent in snapshot.agents:
        style = _status_style(agent.status)
        agents.add_row(agent.label, f"[{style}]{agent.status}[/]")
    subtitle = Text(f"{completed} of {total} agent stages completed")
    return Panel(Group(agents, subtitle), title="Agent Board", border_style="blue")


def _render_messages(snapshot):
    messages = Table(title="Recent Messages", expand=True)
    messages.add_column("Time", width=8)
    messages.add_column("Kind", width=8)
    messages.add_column("Content")
    for item in snapshot.messages[-8:]:
        messages.add_row(item.timestamp, item.kind, _clip(item.content, 180))
    return Panel(messages, title="Activity Feed", border_style="magenta")


def _render_tool_calls(snapshot):
    tools = Table(title="Latest Tool Calls", expand=True)
    tools.add_column("Time", width=8)
    tools.add_column("Tool", width=24)
    tools.add_column("Args")
    for item in snapshot.tool_calls[-6:]:
        tools.add_row(item.timestamp, item.name, _clip(item.args, 120))
    return Panel(tools, title="Tool Traffic", border_style="yellow")


def _render_reports(snapshot):
    populated = [report for report in snapshot.reports if str(report.content or "").strip()]
    if not populated:
        return Panel("No report sections have been produced yet.", title="Report Preview", border_style="green")

    table = Table(expand=True, show_header=True)
    table.add_column("Section", width=28)
    table.add_column("Preview")
    for report in populated[-4:]:
        table.add_row(report.label, _clip(report.content, 220))
    latest = populated[-1]
    preview = Markdown(latest.content[:1200]) if str(latest.content or "").strip() else Text("-")
    return Panel(Group(table, Text(""), Panel(preview, title=f"Latest: {latest.label}")), title="Report Preview", border_style="green")

def _render_dashboard(snapshot, stats: RunStatistics):
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=8),
        Layout(name="body"),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=7),
        Layout(name="right", ratio=5),
    )
    layout["left"].split_column(
        Layout(name="reports", ratio=5),
        Layout(name="messages", ratio=4),
    )
    layout["right"].split_column(
        Layout(name="agents", ratio=4),
        Layout(name="tools", ratio=4),
    )

    layout["header"].update(_render_overview(snapshot, stats))
    layout["left"]["reports"].update(_render_reports(snapshot))
    layout["left"]["messages"].update(_render_messages(snapshot))
    layout["right"]["agents"].update(_render_agents(snapshot))
    layout["right"]["tools"].update(_render_tool_calls(snapshot))
    layout["footer"].update(Panel(Text(format_run_statistics(stats)), title="Stats", border_style="white"))
    return layout


def run_analyze(options: AnalyzeOptions) -> int:
    workflow = workflow_from_storage_root(options.storage_root)
    request = build_analysis_request(options)
    stats = StatsCallbackHandler()
    final_snapshot = None

    if options.emit_json:
        try:
            for snapshot in workflow.stream(request):
                final_snapshot = snapshot
                stats.observe_snapshot(snapshot)
                console.print(f"[{snapshot.status}] {snapshot.latest_update}")
        except Exception as exc:
            console.print(f"analysis failed: {exc}", style="bold red")
            return 1
    else:
        with Live(console=console, refresh_per_second=8, transient=True) as live:
            try:
                for snapshot in workflow.stream(request):
                    final_snapshot = snapshot
                    stats.observe_snapshot(snapshot)
                    live.update(_render_dashboard(snapshot, stats.get_stats()))
            except Exception as exc:
                console.print(f"analysis failed: {exc}", style="bold red")
                return 1

    if final_snapshot is None:
        console.print("analysis failed: no output", style="bold red")
        return 1

    if options.emit_json:
        console.print(dump_json(final_snapshot.to_dict()))
    else:
        console.print()
        console.print(Panel(final_snapshot.final_decision or "No final decision produced.", title="Final Decision"))
        console.print(format_run_statistics(stats.get_stats()))
    return 0


def run_resolve(options: ResolveOptions) -> int:
    workflow = workflow_from_storage_root(options.storage_root)
    resolution = workflow.resolve_symbol(options.query, options.analysis_date)
    console.print(dump_json(resolution.to_dict()))
    return 0


def run_validate(options: ValidateProviderOptions) -> int:
    workflow = workflow_from_storage_root(options.storage_root)
    request = AnalysisRequest.from_mapping(
        {
            "ticker": "NVDA",
            "analysis_date": DEFAULT_ANALYSIS_DATE,
            "llm_provider": options.llm_provider,
            "api_key": options.api_key,
            "quick_model": options.quick_model,
            "deep_model": options.deep_model,
            "base_url": options.base_url,
            "google_thinking_level": options.google_thinking_level,
            "openai_reasoning_effort": options.openai_reasoning_effort,
            "anthropic_effort": options.anthropic_effort,
            "analysts": ["market"],
        }
    )
    ok, message = workflow.validate_provider(request)
    console.print(dump_json({"valid": ok, "message": message}))
    return 0 if ok else 1


def run_serve(options: ServeOptions) -> int:
    run_web_app(host=options.host, port=options.port, storage_root=resolve_storage_root(options.storage_root))
    return 0


@app.command("interactive")
def interactive_command(
    storage_root: str = typer.Option("", "--storage-root"),
) -> None:
    _display_announcements()
    try:
        options = build_interactive_analyze_options(storage_root=storage_root)
    except PromptAborted as exc:
        console.print(str(exc), style="bold red")
        raise typer.Exit(1)
    exit_code = run_analyze(options)
    raise typer.Exit(exit_code)


@app.command("analyze")
def analyze_command(
    ticker: str,
    date: str = typer.Option(..., "--date", help="Analysis date in YYYY-MM-DD format."),
    llm_provider: str = typer.Option("openai", "--llm-provider"),
    api_key: str = typer.Option("", "--api-key"),
    quick_model: str = typer.Option("gpt-5.4-mini", "--quick-model"),
    deep_model: str = typer.Option("gpt-5.4", "--deep-model"),
    language: str = typer.Option("English", "--language"),
    base_url: str = typer.Option("", "--base-url"),
    google_thinking_level: str = typer.Option("", "--google-thinking-level"),
    openai_reasoning_effort: str = typer.Option("", "--openai-reasoning-effort"),
    anthropic_effort: str = typer.Option("", "--anthropic-effort"),
    analyst: list[str] = typer.Option(None, "--analyst"),
    research_depth: int = typer.Option(1, "--research-depth", min=1, max=5),
    checkpoint: bool = typer.Option(False, "--checkpoint"),
    storage_root: str = typer.Option("", "--storage-root"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _display_announcements()
    exit_code = run_analyze(
        AnalyzeOptions(
            ticker=ticker,
            analysis_date=date,
            llm_provider=llm_provider,
            api_key=api_key,
            quick_model=quick_model,
            deep_model=deep_model,
            output_language=language,
            base_url=base_url,
            google_thinking_level=google_thinking_level,
            openai_reasoning_effort=openai_reasoning_effort,
            anthropic_effort=anthropic_effort,
            analysts=analyst or list(DEFAULT_CLI_ANALYSTS),
            research_depth=research_depth,
            checkpoint_enabled=checkpoint,
            storage_root=storage_root,
            emit_json=json_output,
        )
    )
    raise typer.Exit(exit_code)


@app.command("resolve")
def resolve_command(
    query: str,
    date: str = typer.Option(DEFAULT_ANALYSIS_DATE, "--date"),
    storage_root: str = typer.Option("", "--storage-root"),
) -> None:
    _display_announcements()
    exit_code = run_resolve(ResolveOptions(query=query, analysis_date=date, storage_root=storage_root))
    raise typer.Exit(exit_code)


@app.command("validate-provider")
def validate_provider_command(
    llm_provider: str = typer.Option("openai", "--llm-provider"),
    api_key: str = typer.Option("", "--api-key"),
    quick_model: str = typer.Option("gpt-5.4-mini", "--quick-model"),
    deep_model: str = typer.Option("gpt-5.4", "--deep-model"),
    base_url: str = typer.Option("", "--base-url"),
    google_thinking_level: str = typer.Option("", "--google-thinking-level"),
    openai_reasoning_effort: str = typer.Option("", "--openai-reasoning-effort"),
    anthropic_effort: str = typer.Option("", "--anthropic-effort"),
    storage_root: str = typer.Option("", "--storage-root"),
) -> None:
    _display_announcements()
    exit_code = run_validate(
        ValidateProviderOptions(
            llm_provider=llm_provider,
            api_key=api_key,
            quick_model=quick_model,
            deep_model=deep_model,
            base_url=base_url,
            google_thinking_level=google_thinking_level,
            openai_reasoning_effort=openai_reasoning_effort,
            anthropic_effort=anthropic_effort,
            storage_root=storage_root,
        )
    )
    raise typer.Exit(exit_code)


@app.command("serve")
def serve_command(
    host: str = typer.Option(DEFAULT_HOST, "--host"),
    port: int = typer.Option(DEFAULT_PORT, "--port"),
    storage_root: str = typer.Option("", "--storage-root"),
) -> None:
    _display_announcements()
    exit_code = run_serve(ServeOptions(host=host, port=port, storage_root=storage_root))
    raise typer.Exit(exit_code)


def main(argv: Optional[list[str]] = None) -> int:
    try:
        app(args=argv, prog_name=CLI_PROG, standalone_mode=False)
        return 0
    except SystemExit as exc:  # pragma: no cover - delegated CLI exit path
        code = exc.code if isinstance(exc.code, int) else 1
        return code
    except typer.Exit as exc:
        return int(exc.exit_code)


def build_parser():
    raise RuntimeError("The CLI now uses Typer; use `marketmind_ai.cli.main.app` or `main()` instead.")
