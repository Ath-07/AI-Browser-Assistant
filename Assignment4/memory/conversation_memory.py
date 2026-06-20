from langchain.memory import ConversationBufferMemory # type: ignore

memory = ConversationBufferMemory(
    memory_key="chat_history",
    return_messages=True
)