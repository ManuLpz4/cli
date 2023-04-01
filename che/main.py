from typing import Optional
import openai
import os
import platform
import typer
import pyperclip
import pickle
import json
from langchain.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings
from langchain.docstore.document import Document

openai.api_key = os.getenv("OPENAI_API_KEY")

DATA_DIR = "./data"
PLUGINS_DIR = "plugins"
PLUGINS_FILE = "plugins.json"
THRESHOLD = 0.45

app = typer.Typer()

def is_unix_system():
    return platform.system().lower().startswith("lin") or platform.system().lower().startswith("dar")


# Show terminal options
if is_unix_system():
    from simple_term_menu import TerminalMenu
elif platform.system().lower().startswith("win"):
    import inquirer


@app.command()
def main(gen_plugins: bool = typer.Option(False, help="Generate plugin embeddings from `plugins.json`"), prompt: Optional[str] = typer.Argument("", help="The prompt to use")):
    if gen_plugins:
        generate_plugin_embeddings()
        return

    is_user_satisfied = None

    plugin_name = check_if_plugin_call(prompt)

    if plugin_name != None:
        # Call OpenAI API with the plugin path, description and prompt to get the command to execute along with its parameters
        command = get_executable_command(prompt, plugin_name)
        typer.launch(command)
        return

    try:
        while is_user_satisfied == None or not is_user_satisfied:
            if (is_user_satisfied == False):
                corrections = input("Indicaciones adicionales: ")
                prompt += f". {corrections}"
            
            answer = get_answer_from_api(prompt)

            explanation = None
            is_user_satisfied = True

            typer.echo(answer)
            typer.echo("\n")

            # What to do with the answer

            options = ["Ejecutar", "Copiar", "Explicar", "Corregir", "Salir"]

            menu_entry_index = None

            while menu_entry_index == None or options[menu_entry_index] == "Explicar":
                menu_entry_index = get_menu_selection(options)

                if menu_entry_index == 0:
                    os.system(answer)
                    typer.echo("\n")
                elif menu_entry_index == 1:
                    print("> copied")
                    pyperclip.copy(answer)
                elif menu_entry_index == 2:
                    explanation = get_command_explanation(answer)
                    typer.echo(explanation)
                    typer.echo("\n")
                elif menu_entry_index == 3:
                    is_user_satisfied = False

    except openai.error.APIError as e:
        print(f"An API error occurred: {e}")
    except openai.error.AuthenticationError as e:
        print(f"An authentication error occurred: {e}")
    except openai.error.InvalidRequestError as e:
        print(f"An invalid request error occurred: {e}")
    except openai.error.RateLimitError as e:
        print(f"A rate limit error occurred: {e}")
    except openai.error.OpenAIError as e:
        print(f"An unknown error occurred: {e}")


def generate_plugin_embeddings():
    with open(PLUGINS_FILE, "rb") as f:
        metadata = json.load(f)
        executables = metadata["executables"]
        apis = metadata["apis"]
        for plugin in executables + apis:
            if not os.path.isfile(os.path.join(DATA_DIR, f"{plugin['name']}.pickle")):
                plugin_name = plugin["name"]
                store = FAISS.from_documents([Document(page_content=plugin["description"], metadata={"plugin_name": plugin_name})], OpenAIEmbeddings(openai_api_key=openai.api_key))
                with open(f"{DATA_DIR}/{plugin_name}.pickle", "wb") as f:
                    pickle.dump(store, f)


def check_if_plugin_call(prompt):
    descriptions = []
    for filename in os.listdir(DATA_DIR):
        file_path = os.path.join(DATA_DIR, filename)
        if os.path.isfile(file_path):
            with open(file_path, "rb") as f:
                store = pickle.load(f)
                description = store.similarity_search_with_score(prompt, k=1)[0]
                descriptions.append(description)
    top_match = sorted(descriptions, key=lambda x: x[1])[0]
    if top_match[1] < THRESHOLD:
        return top_match[0].metadata["plugin_name"]
    return None


def get_executable_command(prompt, plugin_name):
    with open(PLUGINS_FILE, "rb") as f:
        metadata = json.load(f)
        executables = metadata["executables"]
        for executable in executables:
            if executable["name"] == plugin_name:
                path = executable["path"]
                description = executable["description"]
                break
        res = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": f"You are going to receive a path and description of an executable file, along with a user message. Your job is to output the command to execute the executable file, along with its parameters, taking the parameters from the user message. Just ouput the command to execute, and nothing else. Do not make any comments, nor try to talk to the user in any way. Just output the bash command, without any styling or comments. Don't add line breaks or quotes backticks or anything."},
                {"role": "user", "content": f"Executable path: {path}"},
                {"role": "user", "content": f"Executable description: {description}"},
                {"role": "user", "content": prompt},
            ],
        )
        return res["choices"][0]["message"]["content"]


def get_answer_from_api(prompt):
    res = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are an AI Terminal Copilot. Your job is to help users find the right terminal command in a bash shell on Linux. Just output the command the user is looking for, and nothing else. Do not make any comments, nor try to talk to the user in any way. Just output the bash command, iwthout any styling or comments. Don't add line breaks or quotes backticks or anything. If more than one command is requested, concatenate them with && so that they run one after the other. If the user asks for a command that is not possible, just output 'El comportamiento pedido no es posible de realizar actualmente.' instead of any commands."},
            {"role": "user", "content": prompt},
        ],
    )

    return res["choices"][0]["message"]["content"]


def get_menu_selection(options):
    if is_unix_system():
        terminal_menu = TerminalMenu(options)
        menu_entry_index = terminal_menu.show()
    elif platform.system().lower().startswith("win"):
        questions = [
            inquirer.List(
                "menu_entry_index",
                message="Acción a tomar",
                choices=options,
            ),
        ]
        answers = inquirer.prompt(questions)
        menu_entry_index = options.index(answers["menu_entry_index"])
    
    return menu_entry_index


def get_command_explanation(command):
    res = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are going to receive bash commands, along with other text. I want you to extract those bash commands, and output each one of them, separated by a \\n line break. Add a comment to explain in detail what the commands and their flags do."},
            {"role": "user", "content": command},
        ],
    )
    return res["choices"][0]["message"]["content"]