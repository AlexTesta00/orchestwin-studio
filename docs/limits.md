# Limits and future work

The biggest limit is also the simplest to state. As of 11 October 2026 no session with people has taken place, and everything I know about the Studio's usability and the quality of its designs comes from my own judgement, from the twins or from the software's measures.

## Validation

There are no data on usability, on the quality of the designs or on how what the twins say compares with what people would say. The protocols of the two tests are ready; still missing are the consent approved by the supervisors, the participants, the raters and the material for the eBRT case. The page on [validation with people](validation.md) explains what it takes to begin and what the tests will be able to say.

## Design

There is only one judgement on the quality of the designs, mine, given on synthetic projects, with one generation per condition and no independent raters. On 4 October 2026 I liked the gym project drawn with the visual directions very much. On 10 October 2026 I found the more polished mockups of sprint 45 less beautiful than those of sprint 38, and the same day I chose the Apple style as the standard. My judgement on the comparison of the three alternatives of the gym project is not recorded. That is why the goal of quality and variety is not declared reached.

The [distance measure](design/measures.md) between the alternatives helps, but it looks at one thing only. The verdict is computed on the drawn style, with a threshold of 45 out of 100, and it gives no weight to serif or sans-serif type or to the layout of the text. That is why in sprint 38 the pair of the test calculator got the verdict "Too close" even though it looked different to the eye. With the three alternatives of 10 October 2026, the pairs of the gym project stand at 92, 71 and 39. That is a single project, and the pair formed by the editorial direction and the Apple one stays below the threshold.

Four gaps remain in the process that produces alternatives and mockups. Adherence to the direction is measured, not enforced: in the gym project the mockup of DES-003 does not follow its direction on shapes and colour, and nothing stops it. The instruction forbids gradients, while the contract and the validators accept them, except repeating or conic ones on backgrounds. The twins' critiques of the alternatives come out of the same call that writes the alternatives, so they are a self-assessment, and twins and designs come from the same model. The free directions do not stay clear of the axes of the Apple system: only the instruction keeps them away.

## Traceability

The ["Why?"](framework/why.md) links every artifact to its origin, but a chain is worth as much as its sources. On 2 October 2026, on the calculator used for the measures, 384 artifacts out of 384 reached a twin and none reached active evidence. The entry "Reaches active evidence" also treats any recorded quotation as active, even one from a non-empirical source. To know what has been verified with people you have to look at the state of the hypotheses, not at that entry.

## Command line and web

Three known defects are open. The first affects `ut status`: `sessions.json` can keep a saved sign-in for the Studio on port 8000, made with an account from earlier trials. From a folder linked to that address the command then answers "State read from this folder: the Studio http://127.0.0.1:8000 does not find this project for your account". The remedy is a `ut logout` for that address. When the first design is born, the CLI estimates the spending on two mockups even though three are drawn. And with three alternatives, the web's "Why?", `ut why` and `design.md` still say that a direction was chosen "because it is far from the other".

## Persistence

Sprint 46 deleted the `training` package, not its tables. `training_dataset_versions`, `training_dataset_quality_reports`, `training_runs` and `training_run_checkpoints`, created by migrations 0030 and 0031, stay in the schema with no code that uses them. Removing them takes a new [migration](architecture/persistence.md), which I have not decided on.

## Continuous integration

The test job on Windows took between 37 and 45 minutes depending on the machine, and the limit was 45. On 11 October 2026 a run of the sprint 46 pull request stopped at the limit, after 45 minutes and 15 seconds, with the PostgreSQL suite cut short; the same day I raised the limit to 75 minutes. One dependency remains. This documentation is published after the [release](quality/ci.md), and the release starts only after the `test` and `build` jobs on the three systems: if the Windows job fails, the documentation does not go out. Today `main` has 31 commits after v1.2.0 of 5 October 2026 and no new version.

## Method

The measures of the sprints are checks that things work, not evaluations. The comparisons were made on synthetic briefs, with one generation per condition and per project and no repetitions, so their numbers carry no statistical meaning. The same kind of model draws the alternatives, speaks in the twins' voice and helped me run the measures. A counter-report I asked an assistant for on 1 October 2026 called this a risk of circularity; the planned answer is the two tests, with independent raters and real people.

## The work ahead

There are three dates, all still to come. On 15 October 2026 there is the demo for the supervisors: ten minutes on the Calcolatrice iPhone, the iPhone-style calculator, with no live generations and with the results of the runs already made. After this documentation comes sprint 48, devoted to the tests with people. Test 1 waits for the approved consent and the participants, test 2 for the eBRT material and the raters as well. The thesis is due by 13 November 2026.

Some ideas are left for later. On 6 October 2026 I told the supervisors that an interactive mockup with drag and drop would not fit before the deadline, and on 8 October 2026 point and ask, the "Point at an element" gesture, arrived in its place. The design system is chosen for the whole Studio and only `apple-hig` has its own texts: choosing it project by project is postponed. The free directions should be kept away from the axes of the Apple system by a rule in the code, rather than by the instruction alone.
