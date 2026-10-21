# Semântica global, perfil privado e matching V1

Vocabulário profissional versionado de atributos (nomes canônicos no schema): competência, atividade,
experiência, formação, licença, modalidade, local e vínculo; todas as profissões.
Cada atributo tem nome/valor, base `explicit|inferred|unknown`, confiança [0,1] e
evidências curtas com offsets no insumo. `explicit` exige pelo menos uma citação
que coincida exatamente com o trecho. Evidência fora dos limites ou inventada é
rejeitada. `unknown` não implica requisito negativo nem qualificação do candidato.
Texto da vaga/currículo é dado, nunca instrução para ferramentas, permissões ou tenant.

Classificação global é chaveada por vacancy/content/taxonomy/model/prompt version;
não por usuário. Perfil privado por tenant/geração; matching privado por tenant,
evento, profile_version e policy_version. Sem cache cruzado de conteúdo privado.
Resultados atrasados de versões antigas não substituem projeção atual.

Matching separa elegibilidade objetiva e afinidade. Evento antes da conta, fechado,
retirado ou requisito obrigatório comprovadamente não atendido não é recomendado.
Ausência de informação é incerteza; não se inventa requisito/qualificação nem se
transforma preferência geográfica em veto. Alta/baixa afinidade calibradas depois;
nenhum limiar arbitrário de produção é implantado na 01.

Dados insuficientes de ingestão são rejeitados antes da IA. Resultado ambíguo de
vaga contratualmente válida fica UNCERTAIN; falha/JSON inválido → retry limitado
ou estado de erro, sem score fictício. Jobs têm lease, fencing token e idempotência;
priorizar publicação recente com aging para evitar starvation (definição na 05).

OpenAI: timeout e throttling transitório com backoff/jitter e tentativas limitadas;
quota/limite financeiro/credencial inválida interrompem novas tentativas até ação
externa. Métricas técnicas de tokens/latência/custo não são módulo financeiro interno.
Modelo e custos só serão escolhidos após benchmark autorizado e G-AI.
TTS não é fallback de OpenAI nem utiliza outro provedor silenciosamente.
