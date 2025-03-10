from dotenv import load_dotenv
load_dotenv()

import json
import re
from typing import List, Optional

# (Deprecation 경고를 없애려면):
# from langchain_community.chat_models import ChatOpenAI
# from langchain_community.memory import ConversationBufferMemory
from langchain.chat_models import ChatOpenAI
from langchain.memory import ConversationBufferMemory

from langgraph.graph import StateGraph

# pydantic (2.x 기준)
from pydantic import BaseModel, Field

# -------------------------
# 1) Pydantic 모델 정의
# -------------------------
class MazeState(BaseModel):
    name : str
    setting: str
    atmosphere: str

    quiz : str
    option1 : str
    option2 : str
    option3 : str

    num: str

    step: str = "start"
    message: str = ""

    inventory: List[str] = Field(default_factory=list)
    history: List[str] = Field(default_factory=list)
    story_data: Optional[dict] = None

    # NPC 질문 시 플레이어의 최신 선택
    player_answer: str = ""

# -------------------------
# 2) GPT 모델 설정
# -------------------------
llm = ChatOpenAI(
    model="gpt-4o",   
    temperature=0.7
)
memory = ConversationBufferMemory(return_messages=True)

# -------------------------
# 3) 함수들
# -------------------------

def clean_response(text: str) -> str:
    # 코드 블록 제거
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def generate_story(state: MazeState, name:str, setting:str, atmosphere:str) -> MazeState:
    state.setting = setting
    state.atmosphere = atmosphere
    state.name = name

    prompt = f"""
    게임 개요: 사용자가 설정한 장소와 분위기 기반으로 AI가 세계관과 스토리를 생성하며, NPC와의 상호작용이 중요한 요소입니다.
    플레이어가 미로의 장소로 '{state.setting}', 분위기로 '{state.atmosphere}'를 입력했습니다.
    플레이어의 이름은 {state.name} 입니다.

    무조건 위 게임 개요와 사용자가 입력한 설정을 바탕으로 방탈출게임 느낌의 스토리와 세계관, 목표를 만들어줘. 그리고 npc 3명 만들어줘.
    아래 예시와 똑같이 JSON으로 출력해야 해. 그리고 삼중 백틱(```)이나 다른 코드 블록 문법은 절대 사용하지 마.
    예시 :
    {{
        "world_description": "너가 생성한 세계관 및 스토리 전체 내용",
        "objective": "미로탈출 게임의 세계관 기반 궁극적 목표를 사용자에게 존댓말로 설명",
        "story_details": {{
            "background": 스토리의 시작을 사용자에게 이야기해주듯이 존댓말로 설명",
            "intro": "스토리 초반부 진행 상황 설명을 사용자에게 이야기해주듯이 존댓말로 설명",
            "middle": "스토리 중반부 진행 상황 설명을 사용자에게 이야기해주듯이 존댓말로 설명",
            "final": "스토리 후반부 진행 상황 설명을 사용자에게 이야기해주듯이 존댓말로 설명",
            "result": "스토리 최종결말을 사용자에게 이야기하듯이 존댓말로 작성"
        }},
        "npcs": [
            {{"name": "NPC 이름", "role": "NPC 직업", "personality": "직업에 따른 특징 및 말투"}}
            // 추가 NPC 정보(3명)
        ]
    }}

    위 예시를 무조건 지켜. 부탁할게
    """
    response = llm.invoke(prompt).content
    cleaned_response = clean_response(response)
    try:
        story_data = json.loads(cleaned_response)
    except json.JSONDecodeError:
        state.message = "생성에 실패했습니다."
        raise ValueError("Invalid JSON from LLM response")

    state.story_data = story_data
    state.step = "first_encounter_question"

    # 첫 장면 안내
    background = story_data.get("story_details", {}).get("background", "")
    obj = story_data.get("objective", "")
    state.message = background + "\n" + obj + "\n" + "행운을 빕니다!\n"
    return state


# ---------- [ 첫 번째 NPC: Question 노드 / Followup 노드 ] ----------

def first_encounter_question(state: MazeState) -> MazeState:
    npc = state.story_data["npcs"][0]
    intro_story = state.story_data.get("story_details", {}).get("intro", "")

    prompt_q = f"""
    당신은 이 미로 속에서 플레이어가 만나는 첫 NPC '{npc['name']}' (직업: {npc['role']}) 입니다.
    당신의 말투는 : {npc.get('personality')} 입니다.
    처음에는 '{intro_story}'를 얘기하시고, 그 내용에 기반한 객관적으로 정답이 확실한 3지선다 퀴즈를 1개 내주세요
    틀리면 패널티가 있다는 말을 추가해주세요

    필수 조건 : 
    - **위 내용을 반드시 아래 내용과 동일한 순수한 JSON 형식으로만 출력하세요**
    - 그리고 삼중 백틱(```)이나 다른 코드 블록 문법은 절대 사용하지 마.
    내용:
    {{
        "quiz": "{intro_story}와 퀴즈 질문을 여기에 적어주세요",
        "option1":  "1번 선택지"
        "option2":  "2번 선택지"
        "option3":  "3번 선택지"
    }} 

    """
    question_text = llm.invoke(prompt_q).content
    cleaned_response = clean_response(question_text)
    try:
        data = json.loads(cleaned_response)
        state.quiz = data["quiz"]
        state.option1 = data["option1"]
        state.option2 = data["option2"]
        state.option3 = data["option3"]
    except json.JSONDecodeError:
        state.story = "퀴즈 생성에 실패했습니다. 다시 시도해주세요"

    state.history.append(f"{npc['name']}: {question_text}")
    state.step = "first_encounter_followup"
    return state

def first_encounter_followup(state: MazeState, player_input:str) -> MazeState:
    state.player_answer = player_input.strip()

    npc = state.story_data["npcs"][0]
    player_answer = state.player_answer
    message = state.message.replace("{", "{{").replace("}", "}}")

    prompt_follow = f"""
    당신은 NPC '{npc['name']}' 입니다. 당신의 말투는 : {npc.get('personality')} 입니다.
    플레이어가 '{player_answer}' 라고 답했습니다.
    이전 대화와 퀴즈 내용은 '{message}' 에 존재합니다.

    필수 조건 : 
    - **위 내용을 반드시 아래 내용과 동일한 순수한 JSON 형식으로만 출력하세요**
    - 그리고 삼중 백틱(```)이나 다른 코드 블록 문법은 절대 사용하지 마.


    내용:
    {{
        "message": "플레이어 대답이 맞다면 정답이라는 식으로 한 마디 말하고, 자연스러운 대화를 추가로 한 마디 하고 대화를 끝내세요.
                   틀렸다면 틀렸다고 한 마디 말하고, 자연스러운 대화를 추가로 한 마디 하고 대화를 끝내세요",
        "answer":  "퀴즈를 맞으면 0, 틀리면 1을 문자열로 출력"
    }}    
    """
    follow_text = llm.invoke(prompt_follow).content
    cleaned_response = clean_response(follow_text)

    try:
        data = json.loads(cleaned_response)
        state.message = data["message"]
        state.num = data["answer"]
    except json.JSONDecodeError:
        state.message = "결과 로드에 실패했습니다. 다시 시도해주세요"
    # history 추가
    state.history.append(f"플레이어: {player_answer}")
    state.history.append(f"{npc['name']}: {follow_text}")
    state.step = "second_encounter_question"
    return state


# ---------- [ 두 번째 NPC: Question / Followup ] ----------

def second_encounter_question(state: MazeState) -> MazeState:
    npc = state.story_data["npcs"][1]
    middle_story = state.story_data.get("story_details", {}).get("middle", "")

    prompt_q = f"""
    당신은 이 미로 속에서 플레이어가 만나는 두번째 NPC '{npc['name']}' (직업: {npc['role']}) 입니다.
    당신의 말투는 : {npc.get('personality')} 입니다.
    처음에는 '{middle_story}'를 얘기하시고, 그 내용에 기반한 객관적으로 정답이 확실한 3지선다 퀴즈를 1개 내주세요
    틀리면 패널티가 있다는 말을 추가해주세요

    필수 조건 : 
    - **위 내용을 반드시 아래 내용과 동일한 순수한 JSON 형식으로만 출력하세요**
    - 그리고 삼중 백틱(```)이나 다른 코드 블록 문법은 절대 사용하지 마.
    내용:
    {{
        "quiz": "{middle_story}와 퀴즈 질문을 여기에 적어주세요",
        "option1":  "1번 선택지"
        "option2":  "2번 선택지"
        "option3":  "3번 선택지"
    }} 

    """
    question_text = llm.invoke(prompt_q).content
    cleaned_response = clean_response(question_text)
    try:
        data = json.loads(cleaned_response)
        state.quiz = data["quiz"]
        state.option1 = data["option1"]
        state.option2 = data["option2"]
        state.option3 = data["option3"]
    except json.JSONDecodeError:
        state.story = "퀴즈 생성에 실패했습니다. 다시 시도해주세요"

    state.step = "second_encounter_followup"
    state.history.append(f"{npc['name']}: {question_text}")

    state.message = question_text
    return state

def second_encounter_followup(state: MazeState, player_input:str) -> MazeState:
    state.player_answer = player_input.strip()

    npc = state.story_data["npcs"][1]
    player_answer = state.player_answer
    message = state.message.replace("{", "{{").replace("}", "}}")

    prompt_follow = f"""
    당신은 두 번째 NPC '{npc['name']}' 입니다. 당신의 말투는 : {npc.get('personality')} 입니다.
    플레이어가 '{player_answer}' 라고 답했습니다.
    이전 대화와 퀴즈 내용은 '{message}' 에 존재합니다.

    필수 조건 : 
    - **위 내용을 반드시 아래 내용과 동일한 순수한 JSON 형식으로만 출력하세요**
    - 그리고 삼중 백틱(```)이나 다른 코드 블록 문법은 절대 사용하지 마.

    내용:
    {{
        "message": "플레이어 대답이 맞다면 정답이라는 식으로 한 마디 말하고, 자연스러운 대화를 추가로 한 마디 하고 대화를 끝내세요.
                   틀렸다면 틀렸다고 한 마디 말하고, 자연스러운 대화를 추가로 한 마디 하고 대화를 끝내세요",
        "answer":  "퀴즈를 맞으면 0, 틀리면 1을 문자열로 출력"
    }}  
    """
    follow_text = llm.invoke(prompt_follow).content
    cleaned_response = clean_response(follow_text)
    try:
        data = json.loads(cleaned_response)
        state.message = data["message"]
        state.num = data["answer"]
    except json.JSONDecodeError:
        state.message = "결과 로드에 실패했습니다. 다시 시도해주세요"

    state.history.append(f"플레이어: {player_answer}")
    state.history.append(f"{npc['name']}: {follow_text}")
    state.step = "third_encounter_question"
    return state


# ---------- [ 세 번째 NPC: Question / Followup ] ----------

def third_encounter_question(state: MazeState) -> MazeState:
    npc = state.story_data["npcs"][2]
    final_story = state.story_data.get("story_details", {}).get("final", "")

    prompt_q = f"""
    당신은 이 미로 속에서 플레이어가 만나는 마지막 NPC '{npc['name']}' (직업: {npc['role']}) 입니다.
    당신의 말투는 : {npc.get('personality')} 입니다.
    처음에는 '{final_story}'를 얘기하시고, 그 내용에 기반한 객관적으로 정답이 확실한 3지선다 퀴즈를 1개 내주세요
    틀리면 패널티가 있다는 말을 추가해주세요

    필수 조건 : 
    - **위 내용을 반드시 아래 내용과 동일한 순수한 JSON 형식으로만 출력하세요**
    - 그리고 삼중 백틱(```)이나 다른 코드 블록 문법은 절대 사용하지 마.
    내용:
    {{
        "quiz": "{final_story}와 퀴즈 질문을 여기에 적어주세요",
        "option1":  "1번 선택지"
        "option2":  "2번 선택지"
        "option3":  "3번 선택지"
    }} 

    """
    question_text = llm.invoke(prompt_q).content
    cleaned_response = clean_response(question_text)
    try:
        data = json.loads(cleaned_response)
        state.quiz = data["quiz"]
        state.option1 = data["option1"]
        state.option2 = data["option2"]
        state.option3 = data["option3"]
    except json.JSONDecodeError:
        state.story = "퀴즈 생성에 실패했습니다. 다시 시도해주세요"

    state.step = "third_encounter_followup"
    state.history.append(f"{npc['name']}: {question_text}")
    state.message = question_text
    return state

def third_encounter_followup(state: MazeState, player_input:str) -> MazeState:
    state.player_answer = player_input.strip()

    npc = state.story_data["npcs"][2]
    player_answer = state.player_answer
    message = state.message.replace("{", "{{").replace("}", "}}")

    prompt_follow = f"""
    당신은 마지막 NPC '{npc['name']}' 입니다. 당신의 말투는 : {npc.get('personality')} 입니다.
    플레이어가 '{player_answer}' 라고 답했습니다.
    이전 대화와 퀴즈 내용은 '{message}' 에 존재합니다.

    필수 조건 : 
    - **위 내용을 반드시 아래 내용과 동일한 순수한 JSON 형식으로만 출력하세요**
    - 그리고 삼중 백틱(```)이나 다른 코드 블록 문법은 절대 사용하지 마.

    내용:
    {{
        "message": "플레이어 대답이 맞다면 정답이라는 식으로 한 마디 말하고, 자연스러운 대화를 추가로 한 마디 하고 대화를 끝내세요.
                   틀렸다면 틀렸다고 한 마디 말하고, 자연스러운 대화를 추가로 한 마디 하고 대화를 끝내세요",
        "answer":  "퀴즈를 맞으면 0, 틀리면 1을 문자열로 출력"
    }}
    """
    follow_text = llm.invoke(prompt_follow).content
    cleaned_response = clean_response(follow_text)
    try:
        data = json.loads(cleaned_response)
        state.message = data["message"]
        state.num = data["answer"]
    except json.JSONDecodeError:
        state.message = "결과 로드에 실패했습니다. 다시 시도해주세요"
    # history 추가
    state.history.append(f"플레이어: {player_answer}")
    state.history.append(f"{npc['name']}: {follow_text}")
    state.step = "end_game"
    return state


# ---------- [ 결말 ] ----------
def end_game(state: MazeState) -> MazeState:
    result_story = state.story_data.get("story_details", {}).get("result", "")

    prompt = f"""
    미로의 마지막 장소에 도착했습니다.
    스토리의 최종 결말인 {result_story}를 플레이어에게 자세하게 설명해주세요.
    """
    result_text = llm.invoke(prompt).content
    state.message = result_text
    return state


# -------------------------
# 4) advance_game 함수
# -------------------------
def advance_game(state: MazeState, player_answer:Optional[str]=None) -> MazeState:
    step = state.step

    if step == "start":
        state = generate_story(state, state.name, state.setting, state.atmosphere)

    elif step == "first_encounter_question":
        state = first_encounter_question(state)

    elif step == "first_encounter_followup":
        state = first_encounter_followup(state, player_answer)

    elif step == "second_encounter_question":
        state = second_encounter_question(state)

    elif step == "second_encounter_followup":
        state = second_encounter_followup(state, player_answer)

    elif step == "third_encounter_question":
        state = third_encounter_question(state)

    elif step == "third_encounter_followup":
        state = third_encounter_followup(state, player_answer)

    elif step == "end_game":
        state = end_game(state)

    elif step == "game_finished":
        state.message = "게임이 이미 종료되었습니다."
    else:
        state.message = f"알 수 없는 단계: {step}"

    return state    








# -------------------------
# 4) 실행
# -------------------------
'''
def main():
    setting = input("미로의 장소를 입력하세요 (예: '스위스 산골짜기'):\n> ")
    atmosphere = input("미로의 분위기를 입력하세요 (예: '묘하고 신비로움'):\n> ")

    # Pydantic 모델 생성
    state = MazeState(setting=setting, atmosphere=atmosphere)

    state = generate_story(state)
    print(state.message, flush=True)
    state = first_encounter_question(state)
    print(state.message, flush=True)
    state = first_encounter_followup(state)
    print(state.message, flush=True)
    state = second_encounter_question(state)
    print(state.message, flush=True)
    state = second_encounter_followup(state)
    print(state.message, flush=True)
    state = third_encounter_question(state)
    print(state.message, flush=True)
    state = third_encounter_followup(state)
    print(state.message, flush=True)
    state = end_game(state)
    print(state.message, flush=True)


if __name__ == "__main__":
    main()
'''
