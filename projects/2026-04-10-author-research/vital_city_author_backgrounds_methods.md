# Vital City Author Backgrounds: Method

Created: 2026-04-10

## Scope

This dataset covers unique credited authors found in Vital City's public post metadata.

## Files

- `vital_city_author_backgrounds_provisional.csv`: first-pass classification from Vital City bios only
- `vital_city_author_backgrounds_augmented.csv`: provisional file plus manual overrides for selected high-value ambiguous contributors
- `vital_city_author_backgrounds_summary.csv`: simple counts by primary background and confidence

## Fields

- `author`
- `post_count`: number of credited post appearances in the archive
- `primary_background`: one main professional identity chosen for analytic convenience
- `secondary_backgrounds`: additional relevant identities when visible
- `confidence`: `high`, `medium`, or `low`
- `source_type`: where the classification came from
- `source_url`: page used for the classification when manually overridden
- `bio`: Vital City bio text when available
- `notes`: brief rationale

## Method

1. Pulled all Vital City posts from the public Ghost content API with included author records.
2. Collapsed the archive to unique author records and counted credited appearances.
3. Ran a rule-based keyword classifier on the author bio text to assign provisional categories.
4. Manually overrode a subset of ambiguous but important repeat contributors using clearer contributor pages or outside profiles.

## Confidence

- `high`: explicit professional identity from a contributor page or external profile, or strong multi-keyword match in the Vital City bio
- `medium`: one plausible but less explicit cue in the Vital City bio
- `low`: no strong cue, no bio, or purely residual inference

## Caveats

- Many authors have overlapping identities: e.g. professor-lawyer, journalist-policy analyst, or former official-academic.
- `primary_background` is a simplification for counting, not a full description.
- The manual augmentation pass focused on higher-volume or otherwise salient contributors, not all 435 authors.
- Institutional bylines such as `Vital City`, `A Survey`, and `An Infographic` are included and coded separately as `house/byline`.
