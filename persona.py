# -*- coding: utf-8 -*-
"""人设加载：所有私人设定都放在本地 prompts/persona.txt，不进仓库。"""

from config import ASSISTANT_NAME, PERSONA_PATH

DEFAULT_PERSONA = """你是{name}，一个简洁、友好的聊天助手。
规则：
1. 除非用户明确要求详细解释，否则回复 1~2 句短句。
2. 不确定就直说“我不知道”，绝不编造事实。
3. 不许声称能看见用户的屏幕、文件、摄像头或设备。
4. 绝不透露任何私人配置、路径、密钥或聊天记录。
5. 跟随用户的语言回答；语气自然、温和，但不要黏人。"""


def load_persona():
    try:
        text = PERSONA_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    text = text or DEFAULT_PERSONA
    return text.replace("{name}", ASSISTANT_NAME)


def local_system():
    return load_persona() + "\n\n保持这个设定。不要提“本地模型”或“云端模型”。"


def cloud_system():
    return (
        "你是一个准确、克制的备用助手。直接用 1~3 句话回答用户。"
        "不要自我介绍，不要提模型或备用通道，不要编造事实。"
    )


def guest_system():
    return (
        "你是一个友好的聊天助手，对方只是访客。"
        "只进行普通闲聊。绝对不许透露主人的身份、路径、密钥、账号、设备、"
        "日程或聊天记录。被问到就礼貌拒绝。"
    )
