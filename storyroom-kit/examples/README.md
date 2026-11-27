# Examples

- `sheriff/script.md`: a **fictional** case (every name, place and date is invented). Its wording differs from
  the Javits script: a sheriff's office, a magistrate, a bond and a plea. It gets all six graphics.
  `storyroom-gfx run examples/sheriff/script.md -o out-sheriff`
- `javits/script.md`: the approved Javits Frimpong script from Casefile Studio. `storyroom-gfx plan` places the same
  six graphics as Casefile's demos. The press photos are not included, so graphics with photo slots draw without them.
- `look.json`: a plan-wide look to try with `--look examples/look.json` (graphics over your footage, colour set B
  where offered).
- `words.json`: the word-timing format `--words` reads (the first words of the sheriff script).

Neither example ships with its recording. Without timings, the kit estimates them, which is fine for trying it
out. Give your narration's SRT or word timings for real work.
