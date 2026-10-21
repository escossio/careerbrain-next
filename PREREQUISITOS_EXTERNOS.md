# Pré-requisitos externos — checklist público

Especificação de gates; esta lista não afirma que contas, serviços, credenciais ou
infraestrutura estejam configurados. Evidências operacionais pertencem à custódia privada.

| Dependência | Evidência necessária antes do uso | Gate |
| --- | --- | --- |
| GitHub | histórico inicial novo, PR e proteção de main confirmados pela API | 01 |
| Workers dedicados | capacidade, isolamento e fluxo próprio de teste comprovados | 02 |
| Google OIDC | clientes Android/backend compatíveis, audiência e emissor validados | 03 |
| Produtores de vagas | autorização de uso/exibição e prova de publicação/contato | 04 |
| IA externa | limite financeiro externo, modelo/escopos e tráfego real autorizados | 05/06/07 |
| Privacidade | consentimento, minimização, retenção do provedor e descarte verificados | 06 |
| TTS existente | fronteira dedicada, autorização, custo e privacidade comprovados | uso real |
| Assinatura Android | custódia fora do CI, certificado compatível e operação autorizada | 09/10 |
| Implantação | recursos, volumes, backup externo, restore, HTTPS e rollback comprovados | 10 |

Nenhum valor de credencial, identificador de conta, certificado real, localização de
custódia ou detalhe de rede integra este checklist. Client IDs eventualmente usados
no app devem ser aprovados separadamente para a distribuição correspondente.
O aplicativo nunca recebe segredo de cliente confidencial nem chave de provedor.

Limites de orçamento são administrados no provedor. Alertas não equivalem a bloqueio
rígido e a aplicação de um limite pode ter atraso. A fundação offline não depende
de chamadas reais à IA/TTS nem de credenciais de produção.
