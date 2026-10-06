import { LoginService, UsersService } from "@/client"
import type { UpdatePassword, UserUpdateMe } from "@/client/types.gen"

/**
 * A person's own account: the signed-out flows (registering an organisation, recovering a password)
 * and the signed-in settings. Each is one API call; the server decides everything (open
 * registration, rate limits, token validity, who the caller is).
 */

export interface OrganisationSignup {
  clinic_name: string
  full_name: string
  email: string
  password: string
}

/**
 * `POST /users/signup` with a `clinic_name`: one transaction creates the organisation, the account
 * and its Practice Owner grant. The tenant is created by the server; nothing here names one.
 */
export const registerOrganisation = async (body: OrganisationSignup) => {
  await UsersService.registerUser({ body })
}

/**
 * `POST /password-recovery/{email}`. The server answers the same way whether or not the address
 * has an account, so the caller can only ever say "if it's registered, a link is on its way".
 */
export const requestPasswordRecovery = async (email: string) => {
  await LoginService.recoverPassword({ path: { email } })
}

/** `POST /reset-password/`: spends the emailed token to set a new password. */
export const resetPassword = async (token: string, newPassword: string) => {
  await LoginService.resetPassword({
    body: { token, new_password: newPassword },
  })
}

/** The signed-in account's own settings (`/users/me`). Each acts on the caller only. */
export const updateMe = async (body: UserUpdateMe) =>
  (await UsersService.updateUserMe({ body })).data

export const changePassword = async (body: UpdatePassword) =>
  (await UsersService.updatePasswordMe({ body })).data

/** Deactivates, never deletes: the account and its history are kept; it can't sign in again. */
export const deactivateMe = async () => (await UsersService.deleteUserMe()).data
