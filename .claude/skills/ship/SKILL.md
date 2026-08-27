---
name: ship
description: Close out a shipped roadmap item — remove it from ROADMAP.md and its source (issues.md entry or CLOSING_THE_GAPS.md row), archive its plan doc, confirm the documentation obligations landed, and state what the downstream consumer must do. Use after an item lands, when the user says something "shipped" or "is done", or when ROADMAP.md still lists work that exists in the code.
argument-hint: [what shipped, e.g. "wildcard getters" or "B-2"]
---

Close out a shipped item: **$ARGUMENTS**

[ROADMAP.md](ROADMAP.md) is the single living list of what's *not done yet*,
and it only works if shipping updates it — and so do its two sources,
[issues.md](issues.md) and [CLOSING_THE_GAPS.md](CLOSING_THE_GAPS.md), which
other documents cite by title and row id. Walk every step; several are often
no-ops, but check rather than assume.

1. **Confirm it actually shipped.** Find the implementing code (grep for the
   address or the handler) and confirm it is present on the branch you're
   closing out from; `git log` shows how it got there. Presence in the code
   is the test, *not* a merge to `master` — closing out on the feature
   branch before its PR merges is normal. If the code isn't there, stop and
   say so — never remove roadmap items ahead of reality.

2. **Remove it from [ROADMAP.md](ROADMAP.md).** Delete the entry. If only
   part shipped, rewrite it to just the remainder. If the work surfaced
   follow-ups worth doing later, add them where they fit — with a source
   entry written first (an `issues.md` item or a `CLOSING_THE_GAPS.md` row),
   because the roadmap ranks and never describes.

   **Do not leave a "shipped" banner or recap in ROADMAP.md.** It documents
   future work only; ship history belongs in git, `SESHAT.md`, and the
   archived plan. Renumber the remaining items and any *internal*
   cross-references. Nothing outside ROADMAP.md may cite an item by rank —
   if you notice one, rewrite it to the title.

   Then the **Depends on** notes: any remaining entry that depended on this
   one drops the dependency.

3. **Remove it from its source.** A defect: delete its entry from
   `issues.md` ("Completed entries are removed"). A gap bucket: remove its reference `FORK_GAPS.md` 
   once the gap no longer exists.
   
4. **Confirm the same-commit obligations actually landed** — this is the
   check `/pr-review` made, repeated once more against the final branch,
   because a rebase or a late fix can drop them:
   - every new or changed address has its rows in [API.md](API.md);
   - every divergence from upstream is in [SESHAT.md](SESHAT.md), and any
     edit to an upstream file that would be silently lost in a merge is
     under § Merge hazards;
   - a closed gap's `FORK_GAPS.md` entries are gone and the generated
     inventory was regenerated (`tools/lom_gaps.py`) — the two files must
     not disagree on what is open.

   Anything missing is fixed here, in the close-out commit.

5. **Check the plan's `## Live verification` section before archiving.**
   Every check should carry a dated observation written by whoever ran it.
   A check with nothing under it never ran — say so in the summary, name
   it, and leave the section as it is. Archiving a plan whose checks are
   blank is fine; *implying they passed* is not.

6. **Archive the plan doc.** Move `docs/PLAN_<name>.md` to
   `docs/archive/` (create the directory if needed) and prepend:

   > **Archived YYYY-MM-DD — shipped.** This is the plan as written *before*
   > implementation; the code as merged may differ. <One line on where the
   > change lives now — the handler module and the `API.md` section — and
   > where any still-open follow-ups went.>

   Use today's real date (`date`). **Then fix the links the move broke, in
   both directions**: relative links inside the doc are now one directory
   deeper (`](../` becomes `](../../`; a bare `](API.md)` becomes
   `](../../API.md)`), and every inbound reference in the repo — the
   ROADMAP link above all — is repointed at `docs/archive/<name>.md` or
   removed with the entry.

7. **State the downstream step.** The consumer of this repository is
   Seshat, which pins it as a submodule at `priv/AbletonOSC` and copies the
   tree into Live's Remote Scripts with `mix abletonosc.install`. Nothing
   here can do that for it. Say, from the plan's Downstream section as
   built: pin bump only, or what Seshat must change (decoding, a renamed
   address, a new `vendored_addresses_test` tripwire) — and that the user's
   Live is running the old copy until reinstall and restart.

8. **Verify** with `python3 -m pytest tests_unit/` if anything outside docs
   changed, then summarize: what was removed from the roadmap and its
   source, what was archived, which live checks the plan cited and which of
   those actually ran, what follow-ups were added, and the downstream step.
