export interface ReferenceDocument {
  readonly id: string;
  readonly name: string;
  readonly status: 'ground truth' | 'hypothesis' | 'superseded';
}

export interface BankCandidate {
  readonly id: string;
  readonly phrasing: string;
  readonly priority: number;
}

export interface QuestionBankSection {
  readonly templateSection: string;
  readonly candidates: readonly BankCandidate[];
}

export interface QuestionBank {
  readonly sections: readonly QuestionBankSection[];
}
