# Author Research Workflow

This folder now contains a reusable author-profession research workflow.

## Goal

Identify usable `current profession`, `current employer`, `institution type`, `NYC-based`, and `training/background` fields for every Vital City contributor while preserving the evidence used for each decision.

## Files

- `scripts/build_author_research.py`
- `config/manual_author_overrides.csv`
- `data/raw/vital_city_posts_with_authors.json`
- `data/processed/vital_city_author_master.csv`
- `data/processed/vital_city_author_source_log.csv`
- `data/processed/vital_city_author_review_queue.csv`

## Model

Each author gets:

- `current_profession`
- `current_employer`
- `institution_type`
- `nyc_based`
- `training`
- `secondary_backgrounds`
- `confidence`
- `needs_review`

Each author also gets a row in the source log with the source used for the current classification.

## Notes

- `current_profession` is meant to describe what the person mainly is now, not every credential they hold.
- `current_employer` is the explicit employer or institutional home when it can be recovered from Vital City or a source profile.
- `institution_type` is a coarse bucket: `government`, `nonprofit/advocacy`, `university/research`, `media`, `private company/consulting`, `philanthropy/foundation`, `independent`, `house/byline`, or `unknown`.
- `nyc_based` is `yes` only when a source explicitly places the person in NYC or clearly situates the current role there, `no` when a source explicitly places them elsewhere, and `unknown` otherwise.
- `training` is where we can preserve things like law degrees, architecture background, economics training, etc.
- `manual_author_overrides.csv` is the place to store better evidence from outside profiles as we research more people.
- The review queue is the prioritized list for manual follow-up.
