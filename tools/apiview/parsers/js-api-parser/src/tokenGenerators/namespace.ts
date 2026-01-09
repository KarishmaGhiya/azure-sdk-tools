import { ApiNamespace, ApiItem, ApiItemKind } from "@microsoft/api-extractor-model";
import { ReviewToken, TokenKind } from "../models";
import { TokenGenerator } from "./index";
import { splitAndBuild } from "../jstokens";

function isValid(item: ApiItem): item is ApiNamespace {
  return item.kind === ApiItemKind.Namespace;
}

function generate(item: ApiNamespace, deprecated?: boolean): ReviewToken[] {
  const tokens: ReviewToken[] = [];
  splitAndBuild(tokens, `declare namespace ${item.displayName} `, item, deprecated);
  return tokens;
}

export const namespaceTokenGenerator: TokenGenerator<ApiNamespace> = {
  isValid,
  generate,
};
