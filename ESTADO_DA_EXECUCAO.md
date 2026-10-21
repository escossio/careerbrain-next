# CareerBrain Next — estado da execução

**Estado:** preparação de candidato público; passada 01 BLOQUEADA.
**Contagem:** 1 iniciada, 0/10 validadas. Nenhuma passada posterior autorizada.

| Passada | Escopo | Estado |
| --- | --- | --- |
| 01 | Fundação, contratos, governança e CI | BLOQUEADA: publicação e proteção pendentes |
| 02 | PostgreSQL exclusivo e segurança | NÃO_INICIADA |
| 03 | OIDC e identidade | NÃO_INICIADA |
| 04 | Ingestão autenticada | NÃO_INICIADA |
| 05 | Fila e classificação global | NÃO_INICIADA |
| 06 | Currículo transitório e perfil privado | NÃO_INICIADA |
| 07 | Matching e corte temporal | NÃO_INICIADA |
| 08 | Sincronização, candidaturas e exclusão | NÃO_INICIADA |
| 09 | APK e testes controlados | NÃO_INICIADA |
| 10 | Certificação pública integrada | NÃO_INICIADA |

## Gate imediato

Revisão humana do candidato e autorização de publicação. A futura main exige PR,
checks contracts e repository-policy, bloqueio de force-push/deleção e regras
aplicadas também a administradores. Enquanto houver um mantenedor, aprovação de
outro revisor não será obrigatória. Não fazer merge automaticamente.

## Evidências e limites

Ver docs/evidence-01.md para a verificação local deste candidato. Históricos de
execução anteriores não são evidências públicas desta árvore. A configuração real
no GitHub e as integrações ainda devem ser verificadas quando autorizadas.
A passada 02 requer nova ordem e workers de teste certificados.

## Marco de preparação local

Candidato com 81 arquivos, 21 schemas e 20 exemplos. Testes offline (49) e política de publicação aprovados. Revisão editorial preparada para avaliação do proprietário. Publicação, proteção remota, merge e passada 02 não executados.
