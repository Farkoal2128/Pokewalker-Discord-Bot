"""Generate the offline SI-0 economy report without changing approved settings."""

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content.balance import load_table
from scripts.economy.model import run_scenario


FEATURE = ROOT / "docs/features/pokewalker-bot"
FOOTER = "Numbers above change approved settings only through a README edit by the owner (G-2)"


def display(value):
    return "not observed" if value is None else f"{value:,.2f}"


def render_report(results, *, seed, days, profile, measured, artifact, balances):
    lines = ["# Economy simulation report", "", "## Inputs", "",
             f"- Artifact manifest SHA-256 (`content/manifest.json`): `{hashlib.sha256((ROOT / 'content/manifest.json').read_bytes()).hexdigest()}`",
             f"- Artifact SHA-256 (`content/artifact/content.json`): `{hashlib.sha256((ROOT / 'content/artifact/content.json').read_bytes()).hexdigest()}`",
             f"- Seed: {seed} (reset for each scenario and play style)", f"- Days: {days}",
             f"- Requested profile: {profile}", f"- Profile source: {results[0]['profile_source']}"]
    if results[0]["profile_source"] == "measured percentiles":
        lines.append(f"- Measured summary SHA-256: `{hashlib.sha256(measured.read_bytes()).hexdigest()}`")
    else:
        lines.append("- G-1: no chat export used; adaptation.md fallback profiles are assumptions, not measured behavior.")
    lines.extend(["- Fallback daily profiles: casual 10 messages x 10 words; regular 25 x 12; active 60 x 15. Daily totals are distributed across active hours.",
                  "- Balance table versions:"])
    lines.extend(f"  - {name}.json: v{table['version']}" for name, table in sorted(balances.items()))
    lines.extend(["", "All numbers below use the same requested chat profile at 1, 4 and 8 active hours/day; these are activity-duration scenarios.",
                  "Continuous resolves encounters as a slot is needed; hourly check clears the queue once per active hour.",
                  results[0]["assumptions"] + ". Catches, including virtual catches, stop at full storage (250); no send-to-research is simulated.",
                  "Balls supplied include the starter kit, finds, /checkin and claimed milestones. Item values use the authored conversion rates; Candy is family scoped.",
                  "First-shiny mean/median are geometric estimates from generated encounter pace, not Monte Carlo sample averages or guaranteed catches.", ""])
    for hours in (1, 4, 8):
        pair = [r for r in results if r["active_hours"] == hours]
        lines.extend([f"## {hours} active hours/day", "", "| Metric | continuous | hourly check |", "|---|---:|---:|"])
        metrics = [
            ("Encounters", lambda r: str(r["encounters"])),
            ("Encounters / active hour", lambda r: display(r["encounters_per_active_hour"])),
            ("Balls supplied", lambda r: str(sum(r["balls_supplied"].values()))),
            ("Balls spent (stock-limited)", lambda r: str(sum(r["balls_spent"].values()))),
            ("Candy in (all families)", lambda r: str(r["candy_in"])),
            ("Favourite Candy in", lambda r: str(r["favourite_candy_in"])),
            ("Stardust in", lambda r: str(r["stardust_in"])),
            ("Power-up cost to level 30 (Candy / Stardust)", lambda r: f"{r['powerup_costs']['30']['candy']} / {r['powerup_costs']['30']['stardust']}"),
            ("Power-up cost to level 40 (Candy / Stardust)", lambda r: f"{r['powerup_costs']['40']['candy']} / {r['powerup_costs']['40']['stardust']}"),
            ("Favourite final level", lambda r: display(r["favourite_level"])),
            ("First shiny mean / median (days)", lambda r: f"{display(r['days_to_first_shiny']['mean'])} / {display(r['days_to_first_shiny']['median'])}"),
            ("Observed first shiny day", lambda r: display(r["observed_first_shiny_day"])),
            ("Storage fill day", lambda r: display(r["storage_fill_day"])),
        ]
        for label, value in metrics:
            lines.append(f"| {label} | " + " | ".join(value(r) for r in pair) + " |")
        lines.append("")
    lines.extend(["## D47 comparison", "",
                  "Unmet demand is an estimate: throws the policy would have made with unlimited supply. Virtual throws use the preferred Poke Ball, consume available selected berries, and resolve catches/flees to free queue slots, including Legendary/Mythical encounters.",
                  "Virtual catches also feed progression and milestones; these policy estimates are not predictions of actual stock-limited catches or income.",
                  "Gym assumptions: (a) one 8-hour deployment per day; (b) held all day with immediate re-deployment. One weighted reward pack per full hour held; values below are expected quantities before inventory limits, not simulated gym gameplay.",
                  "All comparison amounts cover the full scenario duration. Deficit = max(0, spent + unmet - supplied); aggregate ball counts treat types as substitutable.", "",
                  "| Hours/day | Style | Supplied | Spent | Unmet demand (estimate) | Demand | Deficit | Stockout encounters | Gym balls (a) | Gym balls (b) | (a) closes deficit? |",
                  "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"])
    for r in results:
        gym = r["gym_income"]
        closes = "no deficit" if not r["deficit"] else "yes" if gym["balls_one_deployment_daily"] >= r["deficit"] else "no"
        lines.append(f"| {r['active_hours']} | {r['style']} | {sum(r['balls_supplied'].values())} | {sum(r['balls_spent'].values())} | {sum(r['unmet_ball_demand'].values())} | {r['ball_demand']} | {r['deficit']} | {r['stockout_events']} | {display(gym['balls_one_deployment_daily'])} | {display(gym['balls_all_day'])} | {closes} |")
    lines.extend(["", "| Gym item | Expected quantity per 8-hour deployment |", "|---|---:|"])
    lines.extend(f"| {item} | {display(quantity)} |" for item, quantity in results[0]["gym_income"]["items_per_deployment"].items())
    lines.extend([f"| **All balls (including Master Ball)** | **{display(results[0]['gym_income']['balls_per_deployment'])}** |", ""])
    arena = results[0]["arena_income"]
    lines.extend(["## Arena ticket income", "",
                  "Reference floors from Arena requirements sections 6.1 and 8 are assumptions, not predictions; no fights are simulated.",
                  "Repeat tickets only, first-clear bonuses excluded. A skip changes fights and payment timing, not total tickets from floors 1 through the cleared floor.",
                  "Encounter totals are upper bounds assuming room at every redemption; fill uses the live queue capacity. Roll values are before inventory limits; encounter value and berry costs are excluded.",
                  "Skip 40 / floor 40 means start and back out: no fights, all tickets paid at start.",
                  f"Cooldown: {balances['arena']['rules']['cooldown_seconds']:,} seconds; {display(arena['runs_per_day'])} runs/day.",
                  f"Income roll value: {display(arena['income_roll_value'])} Stardust; survivor reward value (including flat Stardust): {display(arena['survivor_roll_value'])} Stardust.",
                  "Unpriced items (counted as zero): " + (", ".join(arena["unpriced"]) or "none") + ".",
                  "Arena payouts below are separate from walking/catching income and the existing Checks; no approved Arena income expectation exists.", "",
                  "| Skip | Floor cleared | Fights | Tickets | At start | Encounters (max) | Stardust | Income rolls | Survivor rolls | Stardust-equivalent | At-start Stardust-equivalent | Stardust-equivalent/day |",
                  "|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|"])
    for run in arena["runs"]:
        tickets, at_start = (", ".join(f"{copies} {tier.title()}" for tier, copies in run[key].items()) or "none"
                             for key in ("tickets", "at_start"))
        cells = [str(run["skip"]), str(run["floor"]), str(run["fights"]), tickets, at_start,
                 str(run["encounters_max"]), str(run["stardust"]), str(run["income_rolls"]), str(run["survivor_rolls"]),
                 display(run["stardust_equivalent"]), display(run["at_start_stardust_equivalent"]),
                 display(run["stardust_equivalent"] * arena["runs_per_day"])]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    top = next(r for r in results if r["active_hours"] == 8 and r["style"] == "continuous")
    lines.extend(["## Checks", "",
                  "PASS/FAIL compares these model outputs with the expectations; FAIL does not authorize tuning tables.",
                  "D47: Scarcity is intended. Walking finds plus /checkin deliberately do not fully cover a top-pace player's ball use; gym income is the intended extra source.",
                  f"- **{'PASS' if top['deficit'] > 0 else 'FAIL'} — 8-hour continuous ball shortfall (M0.8): {top['deficit']}.** Actual spending is stock-limited; unmet demand is estimated separately. "
                  + ("This run confirms a shortfall; no values were tuned away." if top["deficit"] else "This profile/seed does not establish the intended top-pace shortfall; no values were tuned to force it."),
                  f"- **{'PASS' if 0 < top['deficit'] <= top['gym_income']['balls_one_deployment_daily'] else 'FAIL'} — gym assumption (a) closes a positive 8-hour continuous deficit.** See both holding assumptions above.", "",
                  "D59: every bundle must be strictly smaller than one month of each scenario's income, compared in stardust equivalent (items plus Stardust; income normalized to 30 days).", "",
                  "| Expectation | continuous | hourly check |", "|---|---|---|"])
    for hours in (1, 4, 8):
        pair = [r for r in results if r["active_hours"] == hours]
        for bundle in pair[0]["bundle_value_vs_income"]:
            cells = []
            for r in pair:
                value = r["bundle_value_vs_income"][bundle]
                amount, income = value["stardust_equivalent"], value["month_income_stardust_equivalent"]
                status = "PASS" if amount < income else "FAIL"
                cells.append(f"{status}: {amount:,.0f} {'<' if amount < income else '>='} {income:,.2f}")
            lines.append(f"| D59 {bundle}, {hours} hours/day | " + " | ".join(cells) + " |")
    lines.extend(["", "Planner expectation (not an approved balance rule): level 30 reachable within 30 days at 4 hours/day.", ""])
    for r in (r for r in results if r["active_hours"] == 4):
        passed = days <= 30 and r["favourite_level"] >= 30
        lines.append(f"- **{'PASS' if passed else 'FAIL'} — {r['style']}**: favourite final level {r['favourite_level']:g} after {days} days. "
                     + ("Reached within 30 days." if passed else "This run does not establish level 30 within 30 days."))
    lines.extend(["", "Failed checks are retained for G-2 owner review. No approved values were changed.", "",
                  "## Legendary pacing", "", "This is a report for the open question, not a decision. Expectations describe appearances before catch time; they do not claim group catches or milestone completion.",
                  "Identity expectations use the Legendary/Mythical tier split; group expectations allow species with multiple identities and measure seeing every member.",
                  "Hours divide expected encounters by this run's continuous generated-encounter pace (1 / 4 / 8 hours/day), not by available balls.", "",
                  "| Identity | Expected encounters | Expected active hours (1 / 4 / 8) |", "|---|---:|---:|"])
    pacing = results[0]["legendary_expected_encounters"]
    identities = {i["identity_id"]: i["name_en"] for i in artifact["identities"]}

    def hours_for(encounters):
        if encounters is None:
            return "unavailable"
        return " / ".join(display(encounters / r["encounters_per_active_hour"]) for r in results if r["style"] == "continuous")

    for identity, expected in pacing["identities"].items():
        lines.append(f"| {identities[identity]} (`{identity}`) | {display(expected)} | {hours_for(expected)} |")
    lines.extend(["", "| Named group (seeing every member) | Expected encounters | Expected active hours (1 / 4 / 8) |", "|---|---:|---:|"])
    for group, expected in pacing["groups"].items():
        lines.append(f"| {group} | {display(expected)} | {hours_for(expected)} |")
    lines.extend(["", "## Route tier pool sizes", "", "| Route | Common | Uncommon | Rare | Evolved | Legendary/Mythical |", "|---|---:|---:|---:|---:|---:|"])
    for route, pools in results[0]["route_tier_pool_sizes"].items():
        lines.append(f"| {route} | " + " | ".join(str(pools.get(tier, 0)) for tier in ("common", "uncommon", "rare", "evolved", "legendary")) + " |")
    lines.extend(["", FOOTER, ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--profile", choices=("measured", "casual", "regular", "active"), default="measured")
    parser.add_argument("--measured", type=Path, default=FEATURE / "measurements/chat-rate-summary.md")
    parser.add_argument("--out", type=Path, default=FEATURE / "economy-report.md")
    args = parser.parse_args(argv)
    if args.days <= 0:
        parser.error("--days must be positive")
    try:
        artifact = json.loads((ROOT / "content/artifact/content.json").read_text(encoding="utf-8"))
        balances = {p.stem: load_table(p.stem) for p in (ROOT / "content/balance").glob("*.json")}
        results = [run_scenario(random.Random(args.seed), active_hours=hours, days=args.days,
                                profile=args.profile, measured_path=args.measured,
                                artifact=artifact, balances=balances, style=style)
                   for hours in (1, 4, 8) for style in ("continuous", "hourly check")]
        report = render_report(results, seed=args.seed, days=args.days, profile=args.profile,
                               measured=args.measured, artifact=artifact, balances=balances)
        args.out.write_text(report, encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(2, f"unable to generate economy report: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
