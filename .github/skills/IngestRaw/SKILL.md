---
name: markdown-ingestor
description: you are to ingest the raw source files from the raw directory within the GE Tools directory and write to the wiki folder, either appending to current pages or adding new ones as you see fit
---

# Location
All of these actions take place in the GE Tools directory, which is located at "C:\Users\19024\Documents\ObsidianVaults\Programming\GE Tools". Consider that the root directory for this skill

# Workflow
- Read a file in the raw directory to get context, ignore files in the "ingested" directory
- Navigate to master_index.md within the wiki directory
- Use this as a starting point for navigation; find your way to the correct sub directory within the wiki directory, then navigate to the index.md file within it. Use that index.md file to find an appropriate file to append to, based on what you read in the raw folder, or if none are suitable, create a new file. link any new files you create inside the index.md file of that directory. After a file in the raw folder has been ingested, move it to the "ingested" folder that lives in the raw folder.

# What your contributions should look like
- High level, conceptual overview of changes / design decisions / implementation stratey. This should go in the correct sub folder (front_end, back_end, ect.)
- Add an entry to the change log "Master Change Log.md" with a quick one to three line summary. Only add another dedicated page within that folder to talk about the change if it was significant.
- Possible bugs or issues that may have been introduced (This is important: make sure all bugs go within the "bugs" folder. Like the change_log folder, add an entry to the "Master Bug List.md" file, and only introduce a dedicated page if it is a major bug. The lising in the master list should link to the dedicated page as well as any other page that is relavent within the wiki folder.)
- If a bug or code base changes and conflicts with an older file in the wiki, update it (delete the fixed bug, update archetecture, ect)
- Suggestions for future changes

# Always do the following
- ALWAYS prioritize a modular wiki. Many small notes is better than few larger ones. You should strive for many ATOMIC, SPECIFIC notes, that way they can be linked when needed to enforce context
- ALWAYS leave a human readable date time stamp attached to content you add, so if you edit multiple sections of a file you should add multiple date time stamps that correspond with your edits.
- Always link any new files you create inside the index.md file of that directory.
- Do not be overly verbose. It is important that this wiki is quickly ingestable for context when making changes. The exception is if a change is a major change, then make sure to go into lots of detail.