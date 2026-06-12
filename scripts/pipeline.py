"""pipeline.py — Unified entry point for the Hilbert salary model pipeline.

Usage:
  python scripts/pipeline.py --all                    # full pipeline
  python scripts/pipeline.py --collect                # crawl + parse only
  python scripts/pipeline.py --step extract           # specific step
  python scripts/pipeline.py --steps extract,normalize,assign  # multiple steps
  python scripts/pipeline.py --all --force            # re-process all
  python scripts/pipeline.py --all --tail-alpha 0.05  # 90% intervals

Steps (in dependency order):
  collect   → crawl + parse new vacancies (via existing Orchestrator)
  filter    → flag non-relevant entries (filter.sql)
  extract   → LLM skill extraction for new vacancies
  normalize → compound split + alias norm + singleton removal
  assign    → map skills to existing cluster taxonomies
  model     → retrain salary model with all data
"""
import argparse, os, sys, time, json

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, ".."))

STEPS_ORDER = ["collect", "filter", "extract", "normalize", "assign", "model"]
STEP_DEPENDS = {
    "filter": ["collect"],
    "extract": ["filter"],
    "normalize": ["extract"],
    "assign": ["normalize"],
    "model": ["assign"],
}


def check_dependencies(steps, force):
    resolved = []
    for s in steps:
        if s in STEP_DEPENDS:
            for dep in STEP_DEPENDS[s]:
                if dep not in resolved and dep not in steps:
                    print(f"  → '{s}' requires '{dep}', adding automatically")
                    resolved.append(dep)
        if s not in resolved:
            resolved.append(s)
    return resolved


def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def step_collect(sources, args):
    print_header("Step: COLLECT — Crawl + Parse")
    from src.config import config
    from src.cli.main import Orchestrator
    orch = Orchestrator(
        sources=sources or config.default_sources,
        queries=None,
    )
    orch.run()


def step_filter(force, args):
    print_header("Step: FILTER — Flag non-relevant entries")
    from src.config import config
    import psycopg2
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    sql_path = os.path.join(BASE_DIR, "filter.sql")
    with open(sql_path) as f:
        sql = f.read()
    conn = psycopg2.connect(config.db_dsn)
    cur = conn.cursor()
    if force:
        cur.execute("UPDATE vacancies SET needs_review = false, review_reasons = NULL")
    cur.execute("""
        SELECT COUNT(*) FROM vacancies WHERE needs_review IS NULL OR needs_review = false
    """)
    total = cur.fetchone()[0]
    if total == 0:
        print("  No unprocessed vacancies")
    else:
        cur.execute("SELECT COUNT(*) FROM vacancies")
        before = cur.fetchone()[0]
        cur.execute(sql.split("-- Step 3:")[0])
        conn.commit()
        cur.execute("""
            SELECT COUNT(*) FROM vacancies
            WHERE needs_review = true AND review_reasons IS NOT NULL
        """)
        flagged = cur.fetchone()[0]
        print(f"  Flagged {flagged} / {before} vacancies for review")
    cur.close()
    conn.close()


def step_extract(force, args):
    print_header("Step: EXTRACT — LLM skill extraction")
    from extract_skills_llm import main as extract_main
    orig_argv = sys.argv
    sys.argv = ["extract_skills_llm.py"]
    if force:
        sys.argv.append("--force")
    extract_main()
    sys.argv = orig_argv


def step_normalize(force, args):
    print_header("Step: NORMALIZE — Prepare hard skills")
    from prepare_hard_skills import main as normalize_main
    orig_argv = sys.argv
    sys.argv = ["prepare_hard_skills.py"]
    if force:
        sys.argv.append("--force")
    normalize_main()
    sys.argv = orig_argv


def step_assign(force, args):
    print_header("Step: ASSIGN — Map skills to cluster taxonomies")
    from assign_clusters import main as assign_main
    orig_argv = sys.argv
    sys.argv = ["assign_clusters.py"]
    if force:
        sys.argv.append("--force")
    assign_main()
    sys.argv = orig_argv


def step_model(force, args):
    print_header("Step: MODEL — Train salary model")
    from src.config import config
    import psycopg2, subprocess
    # First export datasets
    print("  [model] Exporting datasets...")
    subprocess.run([sys.executable, os.path.join(BASE, "export_datasets.py")], check=True)
    # Then train model
    print("  [model] Training salary model...")
    cmd = [sys.executable, os.path.join(BASE, "salary_model.py")]
    if hasattr(args, "tail_alpha") and args.tail_alpha is not None:
        cmd.extend(["--tail-alpha", str(args.tail_alpha)])
    subprocess.run(cmd, check=True)
    print("  [model] Model trained successfully")


STEP_FUNCS = {
    "collect": step_collect,
    "filter": step_filter,
    "extract": step_extract,
    "normalize": step_normalize,
    "assign": step_assign,
    "model": step_model,
}


def main():
    parser = argparse.ArgumentParser(
        description="Hilbert Salary Model Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--all", action="store_true", help="Run all steps")
    parser.add_argument("--collect", action="store_true", help="Crawl + parse only")
    parser.add_argument("--step", help="Run a single step")
    parser.add_argument("--steps", help="Comma-separated steps to run")
    parser.add_argument("--force", action="store_true", help="Re-process all (not incremental)")
    parser.add_argument("--tail-alpha", type=float, default=None, help="Prediction interval tail (passed to salary model)")
    parser.add_argument("--sources", nargs="+", default=None, choices=["hh", "habr", "telegram"],
                        help="Sources for --collect (default: all)")
    args = parser.parse_args()

    start = time.time()

    # Resolve steps
    steps = []
    if args.all:
        steps = list(STEPS_ORDER)
    elif args.collect:
        steps = ["collect"]
    elif args.step:
        steps = [args.step]
    elif args.steps:
        steps = [s.strip() for s in args.steps.split(",")]

    if not steps:
        parser.print_help()
        return

    # Validate
    for s in steps:
        if s not in STEPS_ORDER:
            print(f"Unknown step: {s}")
            sys.exit(1)

    # Check dependencies
    if not args.force:
        steps = check_dependencies(steps, args.force)

    print(f"\n{'#'*60}")
    print(f"#  Hilbert Pipeline")
    print(f"#  Steps: {', '.join(steps)}")
    if args.force:
        print(f"#  Mode: FORCE (re-process all)")
    else:
        print(f"#  Mode: incremental (only new/changed)")
    print(f"{'#'*60}\n")

    for step in steps:
        fn = STEP_FUNCS[step]
        fn(args.force if step != "collect" else False, args)
        elapsed = time.time() - start
        print(f"\n  ✓ {step} done  ({elapsed:.0f}s elapsed)")

    total = time.time() - start
    print(f"\n{'='*60}")
    print(f"  Pipeline complete in {total//60:.0f}m {total%60:.0f}s")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
