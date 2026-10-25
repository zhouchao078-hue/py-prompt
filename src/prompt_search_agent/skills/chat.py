from langchain_deepseek import ChatDeepSeek

from prompt_search_agent.chains.chat_reply import (
    create_chat_reply_chain,
)


class ChatSkillError(RuntimeError):
        pass

class ChatSkill:
    def __init__(self, chat_chain) -> None:
        self.chat_chain = chat_chain

    def invoke(self,user_query: str,intent: str,conversation_context: str,current_prompt: str = "",) -> str:
        reply = self.chat_chain.invoke({
            "user_query": user_query,
            "intent": intent,
            "conversation_context": conversation_context,
            "current_prompt": current_prompt or "暂无",
        })
        reply = reply.strip()
        if not reply:
            raise ChatSkillError("Chat model returned an empty reply")
        return reply

def build_chat_skill(model: ChatDeepSeek) -> ChatSkill:
    chat_chain = create_chat_reply_chain(model)
    return ChatSkill(chat_chain)
