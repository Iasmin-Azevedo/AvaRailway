class IAService:
    def gerar_feedback(self, acertos: int, total: int):
        # Aqui conectaria com OpenAI ou Gemini
        # Por enquanto, é uma lógica simples (Simulação)
        percentual = (acertos / total) * 100
        
        if percentual == 100:
            return "Parabéns! Você dominou esse conteúdo completamente. 🌟"
        elif percentual >= 70:
            return "Muito bom! Você entendeu a maior parte, mas revise os erros. 👍"
        else:
            return "Parece que você teve dificuldades. Que tal revisarmos o material base? 📚"