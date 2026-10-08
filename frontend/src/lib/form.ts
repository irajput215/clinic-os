import type { BaseSyntheticEvent } from "react"
import type { FieldErrors, FieldValues } from "react-hook-form"

/**
 * `handleSubmit`'s `onInvalid` for every form: focus the first invalid field **now**, once.
 *
 * react-hook-form focuses an error field from a `setTimeout` (both `shouldFocusError` and
 * `setFocus` defer it). The deferred focus lands after the person, or a test, has already moved on to
 * another field, and what they type next goes into the field that had the error. CI traced it twice
 * in `tests/staff.spec.ts`: a refused "Confirm password" took the next "Password" text, and a refused
 * invitation's "Full name" text went into "Email". Every form therefore sets
 * `shouldFocusError: false` and passes this, which focuses synchronously, inside the submit.
 *
 * The first invalid field is found in the form's own DOM order, so it is the one the person sees
 * first. A field named `a.b` belongs to the error at `a`. A field with no native control (nothing in
 * `form.elements` carries its name) is simply not focused.
 */
export const focusFirstError = <T extends FieldValues>(
  errors: FieldErrors<T>,
  event?: BaseSyntheticEvent,
) => {
  const form = event?.target
  if (!(form instanceof HTMLFormElement)) return
  const invalid = Object.keys(errors).filter((name) => name !== "root")
  for (const element of Array.from(form.elements)) {
    const name = element.getAttribute("name")
    if (
      name &&
      element instanceof HTMLElement &&
      invalid.some((key) => name === key || name.startsWith(`${key}.`))
    ) {
      element.focus()
      return
    }
  }
}
