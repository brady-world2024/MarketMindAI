import type { ProviderOption, ValidateKeyResponse } from "./api-types";

export type ProviderSettings = {
  provider: string;
  apiKey: string;
  baseUrl: string;
  quickModel: string;
  deepModel: string;
  quickCustom: string;
  deepCustom: string;
  revision: number;
  isValidatingKey: boolean;
  validationResult: ValidateKeyResponse | null;
};

export type SettingsField = "apiKey" | "baseUrl" | "quickModel" | "deepModel" | "quickCustom" | "deepCustom";
export type SettingsAction =
  | { type: "select"; provider: ProviderOption }
  | { type: "edit"; field: SettingsField; value: string }
  | { type: "validation-started"; revision: number }
  | { type: "validation-finished"; revision: number; result: ValidateKeyResponse };

export const initialProviderSettings: ProviderSettings = {
  provider: "", apiKey: "", baseUrl: "", quickModel: "", deepModel: "", quickCustom: "", deepCustom: "",
  revision: 0, isValidatingKey: false, validationResult: null,
};

export function providerSettingsReducer(state: ProviderSettings, action: SettingsAction): ProviderSettings {
  if (action.type === "select") {
    if (state.provider === action.provider.value) return state;
    return {
      ...initialProviderSettings,
      provider: action.provider.value,
      baseUrl: action.provider.base_url ?? "",
      quickModel: action.provider.quick_models[0]?.value ?? "",
      deepModel: action.provider.deep_models[0]?.value ?? "",
      revision: state.revision + 1,
    };
  }
  if (action.type === "edit") {
    if (state[action.field] === action.value) return state;
    return { ...state, [action.field]: action.value, revision: state.revision + 1,
      validationResult: null, isValidatingKey: false };
  }
  // A successful request validates only the exact configuration that started it.
  if (action.revision !== state.revision) return state;
  if (action.type === "validation-started") return { ...state, isValidatingKey: true, validationResult: null };
  return { ...state, isValidatingKey: false, validationResult: action.result };
}
