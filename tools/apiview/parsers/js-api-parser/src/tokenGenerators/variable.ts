import {
  ApiVariable,
  ApiItem,
  ApiItemKind,
  ApiDeclaredItem,
  ExcerptTokenKind,
} from "@microsoft/api-extractor-model";
import { ReviewToken, TokenKind } from "../models";
import { TokenGenerator } from "./index";
import { buildToken, splitAndBuild } from "../jstokens";

function isValid(item: ApiItem): item is ApiVariable {
  return item.kind === ApiItemKind.Variable;
}

function generate(item: ApiVariable, deprecated?: boolean): ReviewToken[] {
  const tokens: ReviewToken[] = [];

  tokens.push(
    buildToken({
      Kind: TokenKind.Keyword,
      Value: "export",
      HasSuffixSpace: true,
      IsDeprecated: deprecated,
    }),
    buildToken({
      Kind: TokenKind.Keyword,
      Value: "const",
      HasSuffixSpace: true,
      IsDeprecated: deprecated,
    }),
  );

  if (item instanceof ApiDeclaredItem) {
    for (const excerpt of item.excerptTokens) {
      if (excerpt.kind === ExcerptTokenKind.Reference && excerpt.canonicalReference) {
        tokens.push(
          buildToken({
            Kind: TokenKind.TypeName,
            NavigateToId: excerpt.canonicalReference.toString(),
            Value: excerpt.text,
            IsDeprecated: deprecated,
          }),
        );
      } else {
        splitAndBuild(tokens, excerpt.text, item, deprecated);
      }
    }
  }

  return tokens;
}

export const variableTokenGenerator: TokenGenerator<ApiVariable> = {
  isValid,
  generate,
};
