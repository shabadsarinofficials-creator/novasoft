
import os
import requests
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

API_KEY = os.getenv("OPENROUTER_API_KEY")

MODEL_A = os.getenv("MODEL_A")
MODEL_B = os.getenv("MODEL_B")
JUDGE_MODEL = os.getenv("JUDGE_MODEL")

API_URL = "https://openrouter.ai/api/v1/chat/completions"


def ask_ai(model, prompt):
    """Send a prompt to an AI model."""

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Answer accurately and clearly. "
                    "Explain important details and state "
                    "uncertainty instead of inventing facts."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.3,
        "max_tokens": 2000
    }

    response = requests.post(
        API_URL,
        headers=headers,
        json=data,
        timeout=120
    )

    response.raise_for_status()
    result = response.json()

    return result["choices"][0]["message"]["content"]


def get_best_answer(question):
    # Ask both AI models at the same time.
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(
            ask_ai, MODEL_A, question
        )
        future_b = executor.submit(
            ask_ai, MODEL_B, question
        )

        answer_a = future_a.result()
        answer_b = future_b.result()

    print("\n========== AI MODEL A ==========")
    print(answer_a)

    print("\n========== AI MODEL B ==========")
    print(answer_b)

    # Give both answers to the judge AI.
    judge_prompt = f"""
You are an expert answer evaluator and synthesizer.

Original question:
{question}

Answer from AI A:
{answer_a}

Answer from AI B:
{answer_b}

YOUR TASK:

1. Identify the strongest useful information in each answer.
2. Combine complementary explanations, examples and insights.
3. Remove repetition and irrelevant information.
4. Check whether the answers contradict each other.
5. Do not automatically assume that both AIs are correct.
6. If they disagree, explain the disagreement and avoid
   presenting an unverified claim as a fact.
7. Correct obvious mistakes when you can do so reliably.
8. If important information is missing, state the limitation.
9. Write one complete, clear and well-organized final answer.
10. Include practical examples when useful.

Return the final answer only.
"""

    final_answer = ask_ai(JUDGE_MODEL, judge_prompt)

    return final_answer


def main():
    if not API_KEY:
        print("ERROR: Add your API key to the .env file.")
        return

    if not all([MODEL_A, MODEL_B, JUDGE_MODEL]):
        print("ERROR: Configure all three model IDs in .env.")
        return

    print("===== AI ANSWER MERGER =====")
    print("Type 'exit' to quit.")

    while True:
        question = input("\nYour question: ").strip()

        if question.lower() == "exit":
            break

        if not question:
            continue

        try:
            print("\nAsking both AIs and comparing answers...")
            answer = get_best_answer(question)

            print("\n========== FINAL ANSWER ==========")
            print(answer)

        except requests.RequestException as error:
            print(f"API request failed: {error}")

        except (KeyError, IndexError, TypeError, ValueError) as error:
            print(f"Unexpected API response: {error}")


if __name__ == "__main__":
    main()
