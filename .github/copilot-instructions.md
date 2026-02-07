# Steps you must always follow
- The very most important thing is to write for maintainability and extensibility. Plan ahead, write code that can be easily built upon and reused in the future
- Prefer Django-native solutions over generic Python patterns.

# Comments (ALLWAYS FOLLOW)
- Every Function, method, and class should have a detailed docstring describing its purpose, its parameters, how it works, and its return value. If there are any edge cases or gotchas that other developers should be aware of when using the function, method, or class, you should
- Any new variable should have a comment describing its purpose and how it is used, especially if its name is not self-explanatory. If the variable is part of a larger block of code, you should also include comments that explain how it fits into the overall logic of the block.
- If you modify existing code, you should be sure to add/modify/delete comments as necessary to explain how the new code works.
- If you come across code that is complex or difficult to understand, you should add comments that explain how it works and why it is written the way it is. You should also consider refactoring the code to make it more readable and easier to understand, if possible.


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

# Rules

1. Always comment your code throughly, especially when there is complex or lengthy logic involved.
2. You should try to keep functions, methods, and classes as concise and short as possible, ideally under 50 lines. If you find yourself writing a function that is longer than 50 lines, you should break it up into smaller functions that are easier to read and understand.
3. You should try to reuse code as much as possible.
4. If you come across code that is lengthy and complex, you should break it into smaller chunks.
5. You are REQUIRED to write django tests for any new functionality you add, and you should also write tests for any existing functionality that you modify. You should aim for 100% test coverage for any code you write or modify. You should also make sure to run your tests and ensure that they all pass before submitting your code for review. More on testing to come, but for now just understand that you need to create a seperate test file for each request i make.

# Development Process
The development process for this agent will be as follows:
1. I will ask you to create a new alert with specific parameters.
2. You will formally describe your understanding of the task, and ask any clarifying questions you may have. You will not come up with a plan or write any code yet.
3. I will confirm if you are correct in your understanding of the task. If you are not, I will explain why. We will continue this process until you have a clear understanding of the task. I will answer any clarifying questions you have.
4. Once you have a clear understanding of the task, you will come up with a plan
5. You will then write the code to implement the alert, following the rules outlined above.
6. You will write tests for the new functionality you added, and for any existing functionality you modified.
7. If all tests pass, you will write a detailed description of the additions/deletions/modifications you made and save it in a file called changes.md, in the root directory of the project. This file should be formatted in markdown and should include code snippets where relevant. The description should be detailed enough for another developer to understand exactly what you did and why you did it, without having to read through all of your code. You should also include any relevant information about how to use the new functionality you added, and any potential edge cases or gotchas that other developers should be aware of when using it.
8. If a test doesnt pass, you will debug the issue and fix it until all tests pass. You should also make sure to update your changes.md file with any relevant information about the bug and how you fixed it.


## Final Rule

Before you do any coding, think about what i have asked you to do, take some time to read my code for context, and describe to me your understanding of the task. I want you to explore possibilities for improvements, edge cases, and any decisions we can make on the front end to deliver a better end result that is more maintanable and extensible. after you describe your understanding of the task, i will confirm if you are correct or not. If not, listen to my corrections and once again scan the code before describing your new understanding. We will repeat this until i am satisfied with your comprehension. Then, I expect you to describe your exact plan to me, including the code you will have to change / edit /delete /create. I also expect you to think out side the box, and ask me about things i may have missed or that you might think would be good to also do. Remember the main goal is to write maintanable, extensible code, so i want you to always explore possibilities that enable us to better reuse code and build upon what we make. When you are done with your changes, provide me a verbose, extremely detailed summary of what you have done, including all files changed, and a description of the changes made. If you encountered any challenges or made significant decisions during the task, please include that information in your summary as well. If there are any next steps or recommendations for further improvements, please mention those too.





