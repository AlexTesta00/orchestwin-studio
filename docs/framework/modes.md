# Guided and expert

Until sprint 36 the Studio had a single way of accompanying the people who use it: one step after another, with explanations, designed for someone with no design experience. On 1 October 2026 the second supervisor asked me not to stop there. An experienced designer or researcher does not need introductory explanations; they want to work on the artifacts directly and bring their own. In the supervisor's words, "a UCD expert must therefore be considered a first-class user of the system". The request was not for two interfaces. The same interface can change how much it guides and how much it does on its own.

## What changes

Sprint 36 built the two modes on 3 October 2026. Guided is the mode the Studio describes as "For people with no design experience." The brief comes out of the dialogue, one question at a time. When you approve a step, the Studio prepares the proposals for the next one by itself, and the sections open in order; after the first pass they all stay open.

Expert is "For people who design for a living." Every section is open from the start and the introductory explanations are closed. No model proposal starts unless you ask for it. You can enter the perspectives, the twin profiles, a complete Definition and a prototype of your own, which goes through the same checks as the generated mockups, from two to eight screens. What you supply stays marked as yours and does not become evidence about users. If something is missing you declare it as a gap, and the declaration stays in the history. On a supplied prototype the twins' review and `ut code` are not available, and the Studio says so.

The mode only governs the web interface. The server blocks no route because of the mode, and `ut`, the MCP server and the Visual Studio Code panel do not know about it: they are tools for people who design for a living and for automated tests.

## One choice per account

In sprint 36 the mode was a browser preference, changed with a control on the page. On 4 October 2026, after recording the video for the supervisors, I wrote two sentences. The first: "if I choose guided mode I can't switch to expert mode and vice versa". The second: "I'd like the user who registers to have a screen where they can choose between a guided or an expert tour, and not be able to change it any more". I did not answer the question of whether the first described a defect or the rule I wanted. The old switch was reproduced with automated tests on a copy of the code, and three of its behaviours made it look stuck. The brief kept the form it had before, the automatic preparations did not start again, and after the first pass the switch changed only the sentence under the title.

Since 5 October 2026, with sprint 39, the mode is chosen once, right after registration, on the "How do you want to work?" screen. When the screen opens, neither card is selected. The button says what you are confirming, for example "Confirm: guided mode". Above it, the warning "After you confirm, you will not be able to change mode." makes clear there is no going back. The choice is stored on the server, in an append-only table (migration 0072) with a trigger that rejects updates and deletions; a second choice gets a 409. The project pages keep a read-only note: "Chosen once for this account: it cannot be changed."

Beyond those two sentences, the reason for making the choice final is not written down in the sprint's evidence. The cost is. An account that chooses by mistake stays that way, even for whoever runs the Studio, and showing both modes takes two accounts.

## A synthetic measure, not a usability one

On 3 October 2026, in sprint 36, the two paths were measured by software, without people: two automated runs on synthetic projects, from Perspectives to the approved Definition, with the same brief and the same archetypes.

| Measure | Guided | Expert |
|---|---:|---:|
| Workflow gestures | 6 | 10 |
| Clicks | 6 | 7 |
| Contents pasted in full | 0 | 3 |
| Duration of the automated run | 8.672 s | 5.966 s |

In Guided mode the three requests to the model were served by deterministic generators; in Expert mode the contents were pasted by the test tool. There was no real generation. A paste counts as one gesture and does not measure the time a person takes to write a Definition. These are two single runs with no statistical meaning, and they say nothing about usability. Something may be said after the first test with people, planned for sprint 49. The protocol written on 7 October 2026 proposes, if the supervisors agree, that people without training in user-centred design work in Guided mode and people with it in Expert mode.
