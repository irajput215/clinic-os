import { LoginService, UsersService } from "@/client"
import type { UpdatePassword, UserUpdateMe } from "@/client/types.gen"
import { adoptToken } from "@/lib/session"

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
 * `POST /users/signup` with a `clinic_name` (D-008): the server emails a link and creates nothing
 * yet. It answers every address the same way (a taken one is emailed a notice instead), so the
 * answer says only which attempt this was, for "Send the email again".
 */
export const registerOrganisation = async (body: OrganisationSignup) =>
  (await UsersService.registerUser({ body })).data

/** `POST /users/signup/resend`: that attempt's email again, with a fresh link. Always `202`. */
export const resendSignupEmail = async (requestId: string) => {
  await UsersService.resendSignupEmail({ body: { request_id: requestId } })
}

/**
 * `POST /users/signup/verify`: spends the emailed link, which creates the organisation and its
 * owner, and keeps the session the server answers with, so the person is signed in.
 */
export const verifySignup = async (token: string) => {
  const { data } = await UsersService.verifySignup({ body: { token } })
  adoptToken(data.access_token)
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

/**
 * `POST /users/invitations/accept`: spends the emailed invitation token to set the invitee's own
 * password. Answers with the account's email, so the page can sign the person straight in.
 */
export const acceptInvitation = async (token: string, newPassword: string) =>
  (
    await UsersService.acceptInvitation({
      body: { token, new_password: newPassword },
    })
  ).data

/** The signed-in account's own settings (`/users/me`). Each acts on the caller only. */
export const updateMe = async (body: UserUpdateMe) =>
  (await UsersService.updateUserMe({ body })).data

export const changePassword = async (body: UpdatePassword) =>
  (await UsersService.updatePasswordMe({ body })).data

/** Deactivates, never deletes: the account and its history are kept; it can't sign in again. */
export const deactivateMe = async () => (await UsersService.deleteUserMe()).data
