# CareerBrain Next — estado da execução

Este checkpoint assume efeito de conclusão na main somente depois dos checks
obrigatórios verdes e merge protegido do PR da passada 02. Na branch de trabalho,
o aceite SQL está comprovado; CI/merge continuam sendo condições explícitas.

| Passada | Estado resultante do merge |
| --- | --- |
| 01 | CERTIFICADA E MERGED; 49 testes e dois checks aprovados |
| 02 | CERTIFICADA E MERGED; 18 testes SQL e restore/ledger aprovados |
| 03 | AUTORIZADA a iniciar após a 02; exige seus próprios gates |
| 04–10 | NÃO_AUTORIZADAS nesta sequência |

**Após merge: 2/10 validadas.** Não confundir a implementação da branch com a
certificação final: o PR/CI é a prova pública de atendimento às condições acima.
Evidências em docs/evidence-02.md; inventários e logs operacionais ficam privados.
A autorização sequencial não permite novo custo, credencial, produção, deploy ou
mudança de produto. A auditoria geral de Apps foi retirada dos gates pelo proprietário.
