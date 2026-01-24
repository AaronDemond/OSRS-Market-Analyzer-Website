# Steps you must always follow
- The very most important thing is to write for maintainability and extensibility. Plan ahead, write code that can be easily built upon and reused in the future
- Prefer Django-native solutions over generic Python patterns.

# Comments (ALLWAYS FOLLOW)
- Write LONG AND DETAILED comments, on all changes. Be as descriptive as possible, and assume you are writing for someone who has never seen the code before.
- Always comment your code, with the following four topics:
  1. What the code does
  2. Why the code is needed
  3. How the code works
  4. Any new variable must be given a comment explaining its purpose.
- if your code interacts with existing code that does not have any comments, add comments to explain how that uncommented codes works aswell.

# Testing
- Do not run python or django tests unless explicitly asked.
- If I ask for tests to be made for a new feature or extension, write tests that follow the django framework protocol and run the new tests along with any previous tests you have written to ensure nothing is broken. Read me the results of your tests.

# After completing a task (VERY IMPORTANT> ALWAYS FOLLOW THESE RULES)
- After completing a task, always provide a thorough summary of what you have done, including what files you have changed and a summary of the changes applied. 
- any important details or considerations for future development.
- If you encountered any challenges or made significant (Changes that are in the hundreds of lines) decisions during the task, please include that information in your summary as well.
- If there are any next steps or recommendations for further improvements, please mention those too.

## Templates
- Assume templates may include `{% %}` and `{{ }}` blocks.
- Do not break Django template syntax when formatting HTML.
- Prefer template inheritance over duplication.

## Migrations
- Always ask for confirmation before creating or applying migrations.
- Assum migrations must be reversible, and you must be ready to provide a way to roll back the migration if needed.

## Maintainability
- Always consider future maintainability of the code you write, and assume more features will be added later. This is a project that will continue to grow and become more complex, so think into the future of how the code you write can be used for more complex tasks. It is better to over-prepare than write something that will have to be roughly patched or completely re written in the future.
- Avoid writing relatively similar code in different places, instead, create reusable functions, classes, or modules. If you see that code is about to become duplicated, refactor it into a single reusable component.
- If writing more lines of code in one place can save writing more lines of code in multiple other places, prefer the longer solution.

## Final Rule

Before you do any coding, think about what i have asked you to do, take some time to read my code for context, and describe to me your understanding of the task. I want you to explore possibilities for improvements, edge cases, and any decisions we can make on the front end to deliver a better end result that is more maintanable and extensible. after you describe your understanding of the task, i will confirm if you are correct or not. If not, listen to my corrections and once again scan the code before describing your new understanding. We will repeat this until i am satisfied with your comprehension. Then, I expect you to describe your exact plan to me, including the code you will have to change / edit /delete /create. I also expect you to think out side the box, and ask me about things i may have missed or that you might think would be good to also do. Remember the main goal is to write maintanable, extensible code, so i want you to always explore possibilities that enable us to better reuse code and build upon what we make. When you are done with your changes, provide me a verbose, extremely detailed summary of what you have done, including all files changed, and a description of the changes made. If you encountered any challenges or made significant decisions during the task, please include that information in your summary as well. If there are any next steps or recommendations for further improvements, please mention those too.

## Aditional import guidlines to prevent crashes!!! IMPORTANT READ ALWAYS FOLLOW
 1. never run django tests unless explicitly asked.
 2. never create or apply migrations unless explicitly asked.
 3. never run python tests unless explicitly asked.
 4. never run syntax checks
 5. never run git commands
 6. never use managy.py commands


