# Design and evaluation

This step is built so that you never get just one design. You get alternatives that differ from each other, each one tried by the twins, and you choose. The goal of quality and variety in the designs is not declared reached; the measures and the judgements are collected in [Design quality and variety](../design/index.md).

## The alternatives

Once the Definition is approved, press "Prepare the design alternatives". The model writes five candidate visual directions and the Studio keeps the two that lie farthest apart. With the Apple design system, on by default, a third one joins them: DES-003, which follows the Human Interface Guidelines. How the directions and the system come about is told in [Visual directions and the Apple HIG system](../design/directions.md).

Each alternative has a code and a title, "In favour" and "Against", "Try the mockup" and "Choose this one". One is "recommended by the designer", and the one that comes from the design system carries the label "Apple guidelines". "Details of the alternative" opens the approach, the rationale, advantages, trade-offs, workflows, "How it serves the twins" and "Visual direction". As in the Definition, you can switch to the table or to the diagrams.

![The gym project on 10 October, scrolled down to the cards: DES-001 "recommended by the designer", DES-002, and DES-003 with "Apple guidelines", with the mockup previews loaded](../assets/web/web-design-tre-schede.png)

## The mockup

Every alternative has a mockup in HTML. In guided mode the Studio draws it on its own as soon as the alternatives are ready; otherwise you ask for it with "Draw the mockup". It usually takes 5 to 10 minutes. The drawing goes on even if you close the page, and it runs on your Claude subscription without spending credit. On 10 October 2026 the three mockups of the gym project, drawn together, took 10 min 35 s.

"Try the mockup" opens a window with the screens and three widths, "Desktop", "Tablet" and "Phone". You can navigate the mockup. The purple numbers on the screens are the observations of the twins, and the window calls them "hypotheses to weigh, not evidence".

![The mockup of DES-001 of the Calcolatrice iPhone opened with "Try the mockup": the five screens at the top, the widths, the screen ready for the first calculation with the purple numbers and, on the right, "What the twins noticed" with the severity of each observation](../assets/web/web-mockup.png)

## How far apart the alternatives are

Two alternatives that look alike are not a choice. Above the cards, a "Distance between the alternatives" box for each pair measures the style drawn in the mockups, from 0 to 100, and says "They differ" or, below 45, "Too close". In the gym project, on 10 October 2026, the measure gave 92 between DES-001 and DES-002, 71 between DES-001 and DES-003, and 39 between DES-002 and DES-003. For that last pair the page writes "Alternatives DES-002 and DES-003 look alike in the drawn style. You can regenerate them."

![The gym project at step 5 of 6: the "Distance between the alternatives · DES-001 · DES-002" box with "They differ", "5 of 5 axes differ" and the details of the measure open, and at the bottom the bar with "Approve the chosen design"](../assets/web/web-design-distanza.png)

"Details of the measure" keeps the declared choices, the drawn style and the structure of the screens apart, and puts the limit in plain words: "Measure computed by the Studio: it does not replace your judgement." The measure cannot tell a serif typeface from a sans-serif one, and it does not look at how the text is laid out. Its limits are in [Measures](../design/measures.md).

## What the twins think

"What the twins think" is a grid with one row per twin and one column per alternative, under the words "Simulated feedback, not evidence". Each cell holds a short verdict, a sentence from the twin and the number of observations. In the gym project, the twin that stands for members over 60 in the gentle classes finds DES-001 clear and says it feels safe. Open a cell and you read the observations, each with its point on the mockup and a "Suggested action". You answer each one with "I confirm" or "Not relevant", knowing that your confirmation "is a project decision: it is not a check with real people".

![The last rows of the "What the twins think" grid of the Calcolatrice iPhone, with verdicts, sentences from the twins and number of observations, and below it "Synthetic pre-validation" with the comparison between two reviews](../assets/web/web-pre-validazione.png)

## Choosing

"Choose this one" works once the mockup of that alternative is ready, and it creates a new version of the design. Then the twins review the chosen mockup in "Synthetic pre-validation". In guided mode the review starts by itself; in expert mode you ask for it with "Ask the twins to evaluate the design". In the gym project, on 10 October, choosing DES-001 together with the twins' review took 123.6 s.

## Changes in words, and rules

"Ask for changes" opens the field where you write what to change, up to 1,000 characters. The designer draws a new version of the mockup and shows it to you in "Changes you asked for", with "What changed" and the screens to compare. You apply it with "Apply the new version" or leave it with "Discard".

If you tick "Keep it as a rule for the next versions", the request becomes a rule that the designer follows in every new version. A rule can be up to 300 characters long, a design holds up to twenty of them, and each one goes away with "Remove". The Calcolatrice iPhone has had one since 7 October 2026: the digits on the display stay the largest text on the page.

## Pointing at an element, a zone or several elements

A request about a whole screen can be vague, and pointing at the element makes it precise. In the mockup window press "Point at an element" and click what you want to change. The "Elements you can point at" panel lists the elements with their codes; when you pick one it shows the screen, the text and the linked requirements, and asks "What should I change?". With "Ask the twins for their opinion right away" ticked, press "Apply the change", then apply the new version when it arrives.

The opinion appears next to the element, under "What the twins say about it": "Helps", "Slows down" or "Blocks", with a "What to do" that "Try this" copies into the field. On 8 October 2026, on the Calcolatrice iPhone, the request to make the "=" key (ELM-023) dark blue with a white symbol, taller than the other keys, produced the new version in about 5 minutes. The opinion of the three twins arrived in about 2 minutes: "Slows down", "Helps", "Slows down".

![The mockup of the Calcolatrice iPhone with "Point at an element" on: on the right the list "Elements you can point at" with the ELM codes and the hint on how to choose; no element chosen yet](../assets/web/web-mockup-indica.png)

Since 12 October 2026 the list holds zones too. A zone is a container of the page with at least two elements inside, such as the bar at the top, a navigation, the main content, a section, a form, a list or a group of cards. Zones have a series of codes of their own, ZON-001 and onwards, and the list gives their kind in words with the number of elements, such as "group of cards, 31 elements". Move over an empty spot of a bar or a section and the box frames the whole zone. Choose it and the panel says "Holds 31 elements", with the first three listed. When the part you chose sits inside a zone, "Choose the zone that holds it" moves the choice one level up.

One request can also cover several parts of the same screen, up to eight. Turn on "Choose several elements" and each click adds or removes a part. With the switch off, Ctrl or ⌘ and a click on the mockup do the same, and so does the space bar in the list. Every chosen part gets its own box on the mockup and a line in the panel, with "Remove" next to it. Esc clears the whole choice. Moving to another screen clears it as well, with the announcement "Choice cleared: the screen changed."

![The mockup of DES-001 of Bottega Vicina with "Point at an element" on and "Choose several elements" ticked: on the first screen the sections "Forno Ravasi" and "Panificio Colombo" are framed with their codes ZON-007 and ZON-009; on the right the list "Elements you can point at" mixes zones and elements, and "Chosen parts" holds the two sections, each with "Remove"](../assets/web/web-mockup-zona.png)

Zone codes follow the order of the document, exactly like element codes, so a new version can renumber them. Before every generation the Studio checks that each code still exists on that screen of the applied mockup, and it refuses the request when one is missing.

Bottega Vicina ("the shop next door") shows what this means on a real page. Its version 3 has six screens and 201 elements, and the Studio finds 61 zones in it, 18 on the first screen. The bar at the top is ZON-001 and the group of producer cards in the middle is ZON-005. Inside that group, the sections "Forno Ravasi" and "Panificio Colombo" are ZON-007 and ZON-009. A supervisor asked on 12 October to show those two bakeries in two rows instead of two columns. That afternoon the request went from the mockup window on version 3, with "Choose several elements" on ZON-007 and ZON-009 and the text written in Italian. The new version came in 5 min 07 s with four changes. The two cards went one under the other at full width, the products moved to one row of four above 960 px, and the introductory band and Bottega Lucana went to full width as well. It was applied as version 4. The review of the twins, aimed at the two zones, took 1 min 46 s and gave "Helps", "Helps" and "Slows down", with the grouping by shop noted as a help for scrolling.

The review by the twins can look at a zone or at several parts as well. It starts by itself after the change when "Ask the twins for their opinion right away" is ticked. Otherwise you ask for it with "Ask the twins for their opinion on this zone" or "Ask the twins for their opinion on these parts". Their notes stay next to what you chose.

## Asking the twins before applying

Some requests are worth discussing before a new version is drawn. Choose the parts, write what to change and press "Ask the twins before applying": the design does not change. It usually takes about 2 minutes, with one generation per twin, and the button stays off while a new version waits for your decision.

Each twin reads the request, the part you pointed at with its text and its markup, the screen as it is today, the palette of the design and the contrast rules the Studio applies. When the request names colours, in words or as hex codes, the Studio also computes their contrast ratios: with each other, with the background of the palette and with its text colour. The twin receives those numbers. When a pair fails, the instruction asks the twin to warn that the text would be hard to read and that the Studio would replace the colour, quoting the ratio and the threshold. It must never invent a ratio.

The answers arrive under "What the twins say before the change", with the note "Opinion simulated by the model: a hypothesis to check with real people." Each twin gives "Helps", "Slows down" or "Blocks", says why, and adds "What to do:" with one concrete step. A twin that would phrase the request differently adds a line, "I would ask for it like this: “…”". "Try this" copies that wording into "What should I change?", or the "What to do" when the twin left the request alone.

Then you decide. "Apply anyway" starts the change with the same text, and the request keeps a link to the opinion. "Change the request" takes you back to the field. "Cancel" empties it and announces "Request cancelled; the opinion stays recorded." An opinion holds for one request on the same parts of the same version. Edit the text, change the choice or let the design move on, and the block warns "The opinion is about a different request: ask for it again or apply the new request with “Apply the change”." From that moment "Apply anyway" is gone.

The opinion before the change does not replace the review after it, which works as it did. Opinions are kept with the generations that produced them, and none of them counts as a review of a version.

The gesture answers the second example of 12 October, and it was tried that afternoon on ZON-001, the bar at the top of Bottega Vicina, with a request written in Italian to make the background red and the text blue. The three twins answered in 35 s. Piccolo produttore locale (the small local producer) and Acquirente di fretta in pausa pranzo (the shopper in a hurry on a lunch break) said "Slows down". Acquirente diffidente verso l'online (the shopper wary of buying online) said "Blocks". All three quoted the ratio computed by the Studio, 2.15:1, below both 4.5:1 and 3:1, and said that the Studio would replace the colour. They proposed the light background of the palette with dark or blue text, at 8.21:1, and red only for details that are not text. The wary shopper added that a bright red recalls promotions and errors.

Then "Apply anyway" sent the same request to the designer. The designer did not carry it out and gave the reasons in its list of changes: the design has no blue, its red is kept for errors, and no text is sure to stay readable on red. The package came back identical, and no new version was created.

## Corrections the Studio made

Before the twins see a new mockup, the Studio checks the contrast of its texts and of the borders of its controls. The thresholds are 4.5:1 for text and 3:1 for large text, 7:1 and 4.5:1 in the high-contrast modes, and 3:1 for the borders of controls. A colour below its threshold is replaced with the nearest colour of the palette that reaches it. Until sprint 48 the Studio said only that it had replaced the colour of a text that was hard to read, without saying which colour or with which one.

Now every replacement is a line under "Corrections made by the Studio". The line starts with "Text of the rule" or "Border of the controls of the rule", followed by the CSS selector. It gives the colour before on its background with their ratio, the minimum that was missed, and the colour that took its place with the new ratio. Colours are named in words with their hex code, such as "white #FFFFFF", and ratios are cut to one decimal. When the rule has no background of its own, the line speaks of "the inherited background"; when the same replacement covers several rules, it ends with their number in brackets.

The lines appear in "Changes you asked for", where a note explains "Before the twins saw the version, the Studio replaced the colours below the contrast thresholds." They come back in "Earlier requests", under "Corrections by the Studio", and in the mockup window they sit under "Apply the new version". In "Technical details", "Notes of the Studio on the mockups" puts them before the other notes. "To check" keeps the remaining warnings and no longer repeats a correction that is already listed. `ut design show` prints the same lines ([ut design](../ut/design.md)). None of the four runs on Bottega Vicina of 12 October set off a correction, because the designer chose or kept readable colours by itself, so the block has not appeared in a real case yet.

For the colours of a mockup there are no silent corrections any more. The palette that the model writes with the alternatives is another matter, described in [Limits and future work](../limits.md#point-and-ask).

## Versions of the design

Above the alternatives sits a collapsed block, "Versions of the design", with the date of each version, the "current" one marked, and notes such as "Restored from version 9". "Go back to this version" deletes nothing and does not call the model: it creates a new version identical to the one you picked, which you then approve. On 8 October 2026, going back to version 10 of the Calcolatrice iPhone created version 12 in 2.0 s. The Studio refuses to go back if that version cites requirements that no longer exist, or if it was prepared with different twins.

![The Calcolatrice iPhone: "Rules that hold for the next versions" with the rule on the display digits and "Remove", and below it "Versions of the design (13)" open, with version 13 marked "current" and versions 12 and 11 born from a restore](../assets/web/web-versioni-design.png)

## The gesture

You approve with "Approve the chosen design", and the knowledge folder will contain this design and the opinion of the twins. In the step's technical details one sentence says what the gesture is worth: "Owner approval is governance, not empirical validation." Even afterwards you can ask for changes or use "Regenerate the alternatives". The critique of an existing design and the hypotheses to verify with people, which live in this step too, are described in [After the design](after-design.md); the commands are in [ut design](../ut/design.md).
