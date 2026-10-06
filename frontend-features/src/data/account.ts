import { UsersService } from "@/client"
import type { UpdatePassword, UserUpdateMe } from "@/client/types.gen"

/** The signed-in account's own settings (`/users/me`). Each acts on the caller only. */
export const updateMe = async (body: UserUpdateMe) =>
  (await UsersService.updateUserMe({ body })).data

export const changePassword = async (body: UpdatePassword) =>
  (await UsersService.updatePasswordMe({ body })).data

/** Deactivates, never deletes: the account and its history are kept; it can't sign in again. */
export const deactivateMe = async () => (await UsersService.deleteUserMe()).data
