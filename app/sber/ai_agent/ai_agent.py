from langchain_core.prompts import PromptTemplate
from langchain_gigachat.chat_models.gigachat import GigaChat
from langchain.chains import ConversationChain
from langchain.memory import ConversationBufferMemory
from loguru import logger
from app.const import TEMPLATE, MODEL


@logger.catch
def initialize_ai_agent(gigachat_token, model=MODEL) -> ConversationChain:
    llm = GigaChat(access_token=gigachat_token, verify_ssl_certs=False, model=model)
    conversation = ConversationChain(
        llm=llm,
        verbose=True,
        memory=ConversationBufferMemory(),
        prompt=PromptTemplate(input_variables=["history", "input"], template=TEMPLATE),
    )
    return conversation


@logger.catch
def analyze_text(text: str, conversation) -> str:
    """Анализ текста с помощью AI-агента."""
    response = conversation.predict(input=text)
    logger.success(f"AI analysis result: {response}")
    return response
