import type { QueryClient } from "@tanstack/react-query";
import type { User } from "./api";

/**
 * Switch the signed-in user (null = signed out) and drop every other cached answer.
 *
 * The ["me"] query must be updated in place, not removed: queryClient.clear() would detach the
 * observer that App renders from, and the page would never notice the new user.
 */
export function switchUser(queryClient: QueryClient, user: User | null) {
  queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== "me" });
  queryClient.setQueryData(["me"], user);
}
