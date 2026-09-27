"""Mede acoplamento por componente (Ca, Ce, I, A, D) e desenha o gráfico A x I.

Régua (requisito 3 do desafio):
- componente: cada módulo .py sob a pasta medida, incluindo subpastas, exceto __init__.py,
  identificado pelo caminho com pontos relativo a ela (ex.: adapters.gateway);
- dependência: um import, relativo ou absoluto, que resolve para outro componente;
  bibliotecas externas e da biblioteca padrão não contam;
- Ca: quantos componentes importam este; Ce: quantos este importa;
- I = Ce / (Ce + Ca), ou 0 quando os dois são zero;
- A = classes abstratas (herdam de typing.Protocol ou abc.ABC) / total de classes, ou 0 sem classes;
- D = |A + I - 1|; valores arredondados para 2 casas.

Uso:
    python metrics/coupling.py <caminho de app/helpdesk> --name <nome>

Grava metrics/results/<nome>.csv e metrics/results/<nome>.png.
"""

import argparse
import ast
import csv
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

RESULTS_DIR = Path(__file__).parent / "results"
ABSTRACT_BASES = {"Protocol", "typing.Protocol", "ABC", "abc.ABC"}


def discover(root: Path) -> dict[str, Path]:
    """Mapeia o nome com pontos de cada componente para o seu arquivo."""
    components = {}
    for path in sorted(root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        relative = path.relative_to(root).with_suffix("")
        components[".".join(relative.parts)] = path
    return components


def dependencies(name: str, path: Path, components: dict[str, Path], root_package: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = name.split(".")[:-1]  # 'adapters.gateway' -> ['adapters']
    found: set[str] = set()

    def to_component(parts: list[str]) -> str | None:
        """Converte um caminho absoluto (sem o pacote raiz) num componente, se existir."""
        candidate = ".".join(parts)
        return candidate if candidate in components else None

    def strip_root(dotted: str) -> list[str] | None:
        """'helpdesk.adapters.gateway' -> ['adapters', 'gateway']; outros pacotes -> None."""
        parts = dotted.split(".")
        if parts[0] != root_package:
            return None
        return parts[1:]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = strip_root(alias.name)
                if parts:
                    found.add(to_component(parts))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # from . import x / from ..ports import y: sobe (level - 1) pacotes
                if node.level - 1 > len(package):
                    continue
                base = package[: len(package) - (node.level - 1)]
                module = base + (node.module.split(".") if node.module else [])
            else:
                if node.module is None:
                    continue
                module = strip_root(node.module)
                if module is None:
                    continue
            found.add(to_component(module))
            # from pacote import modulo: cada nome importado pode ser um componente
            for alias in node.names:
                found.add(to_component(module + [alias.name]))

    found.discard(None)
    found.discard(name)
    return found


def base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Subscript):  # Protocol[T]
        return base_name(node.value)
    if isinstance(node, ast.Attribute):
        return f"{base_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Name):
        return node.id
    return ""


def abstractness(path: Path) -> float:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    if not classes:
        return 0.0
    abstract = [c for c in classes if any(base_name(b) in ABSTRACT_BASES for b in c.bases)]
    return len(abstract) / len(classes)


def round2(value: float) -> Decimal:
    return Decimal(repr(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def measure(root: Path) -> list[dict]:
    root = root.resolve()
    components = discover(root)
    deps = {name: dependencies(name, path, components, root.name) for name, path in components.items()}
    rows = []
    for name, path in components.items():
        ce = len(deps[name])
        ca = sum(1 for other, targets in deps.items() if other != name and name in targets)
        i = ce / (ce + ca) if ce + ca else 0.0
        a = abstractness(path)
        d = abs(a + i - 1)
        rows.append({"component": name, "ca": ca, "ce": ce,
                     "i": round2(i), "a": round2(a), "d": round2(d)})
    return rows


def write_csv(rows: list[dict], target: Path) -> None:
    with target.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["component", "ca", "ce", "i", "a", "d"])
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, **{k: f"{row[k]:.2f}" for k in ("i", "a", "d")}})


def plot(rows: list[dict], title: str, target: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.plot([0, 1], [1, 0], color="#2b6cb0", linewidth=1.5, label="Main Sequence (A + I = 1)")
    ax.fill_between([0, 0.5], [0, 0], [0.5, 0], color="#e53e3e", alpha=0.12,
                    label="Zona de dor (A < 0,5, I < 0,5, D ≥ 0,5)")
    ax.fill_between([0.5, 1], [1, 1], [1, 0.5], color="#dd6b20", alpha=0.12,
                    label="Zona de inutilidade")

    # Componentes com o mesmo (I, A) viram um único ponto com todos os nomes.
    groups: dict[tuple[float, float], list[str]] = {}
    for row in rows:
        groups.setdefault((float(row["i"]), float(row["a"])), []).append(row["component"])
    for index, ((i, a), names) in enumerate(sorted(groups.items())):
        color = "#c53030" if i < 0.5 and a < 0.5 and abs(a + i - 1) >= 0.5 else "#2d3748"
        ax.scatter(i, a, s=60, color=color, zorder=3)
        # Alterna o rótulo acima/abaixo do ponto para vizinhos próximos não se sobreporem.
        above = index % 2 == 0
        ax.annotate("\n".join(sorted(names)), (i, a), textcoords="offset points",
                    xytext=(6, 6 if above else -8), va="bottom" if above else "top",
                    fontsize=8, color=color)

    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("I (instabilidade) = Ce / (Ce + Ca)")
    ax.set_ylabel("A (abstração) = abstratas / classes")
    ax.set_title(f"A x I: {title}")
    ax.grid(True, linewidth=0.3)
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    fig.savefig(target, dpi=120)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path, help="pasta app/helpdesk do checkout a medir")
    parser.add_argument("--name", required=True, help="nome do resultado (ex.: v1-coupled)")
    parser.add_argument("--no-plot", action="store_true", help="grava só o CSV")
    args = parser.parse_args()

    rows = measure(args.path)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(rows, RESULTS_DIR / f"{args.name}.csv")
    if not args.no_plot:
        plot(rows, args.name, RESULTS_DIR / f"{args.name}.png")

    print(f"{'component':<28}{'ca':>4}{'ce':>4}{'i':>6}{'a':>6}{'d':>6}")
    for row in rows:
        pain = "  <- zona de dor" if row["i"] < Decimal("0.5") and row["a"] < Decimal("0.5") \
            and row["d"] >= Decimal("0.5") else ""
        print(f"{row['component']:<28}{row['ca']:>4}{row['ce']:>4}{row['i']:>6}{row['a']:>6}{row['d']:>6}{pain}")


if __name__ == "__main__":
    main()
